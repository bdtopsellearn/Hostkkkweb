"""Safe, provider-neutral infrastructure node primitives.

This module deliberately performs discovery and connectivity tests only. It never
installs packages or runs destructive commands without an explicit caller action.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

STATES = {"AUTHENTICATED", "ONLINE", "OFFLINE", "AUTHENTICATION FAILED", "UNSUPPORTED", "NEEDS CREDENTIALS", "NEEDS SETUP"}


def new_node(name: str, connection_type: str = "local", **fields: Any) -> Dict[str, Any]:
    if connection_type not in {"local", "ssh", "agent"}:
        raise ValueError("connection_type must be local, ssh, or agent")
    return {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "provider": fields.get("provider", ""),
        "connection_type": connection_type,
        "ipv4": fields.get("ipv4", ""),
        "ipv6": fields.get("ipv6", ""),
        "hostname": fields.get("hostname", ""),
        "url": fields.get("url", ""),
        "ssh_port": int(fields.get("ssh_port", 22)),
        "username": fields.get("username", ""),
        "auth_method": fields.get("auth_method", "key"),
        "enabled": bool(fields.get("enabled", True)),
        "status": "NEEDS SETUP",
        "capabilities": {},
        "last_test": None,
        "secret_ref": fields.get("secret_ref", ""),
    }


class CredentialStore:
    """Encrypt node credentials at rest; plaintext exists only in memory."""
    def __init__(self, path: str | Path, key: str):
        self.path = Path(path); self.key = key; self._lock = threading.Lock()
        if not key: raise ValueError("credential encryption key is required")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, str]:
        if not self.path.exists(): return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def put(self, node_id: str, secret: str) -> None:
        with self._lock:
            data = self._load(); data[str(node_id)] = encrypt_secret(secret, self.key)
            self.path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            try: self.path.chmod(0o600)
            except OSError: pass

    def get(self, node_id: str) -> str:
        with self._lock:
            value = self._load().get(str(node_id), "")
        return decrypt_secret(value, self.key) if value else ""

    def delete(self, node_id: str) -> None:
        with self._lock:
            data = self._load(); data.pop(str(node_id), None)
            self.path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def encrypt_secret(value: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_secret(value: str, key: str) -> str:
    return Fernet(key.encode()).decrypt(value.encode()).decode()


def local_capabilities() -> Dict[str, Any]:
    usage = shutil.disk_usage(Path.cwd())
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpuCores": os.cpu_count() or 1,
        "ramBytes": _ram_bytes(),
        "diskBytes": {"total": usage.total, "free": usage.free},
        "docker": shutil.which("docker") is not None,
        "python": platform.python_version(),
    }


def _ram_bytes() -> Optional[int]:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def test_ssh_node(node: Dict[str, Any], secret: str, timeout: int = 8) -> Dict[str, Any]:
    """Authenticate with SSH and run read-only capability probes."""
    try:
        import paramiko
    except ImportError:
        return {"state": "NEEDS SETUP", "reason": "paramiko is not installed"}
    host = node.get("hostname") or node.get("ipv4") or node.get("ipv6")
    if not host or not node.get("username"):
        return {"state": "NEEDS CREDENTIALS", "reason": "SSH host and username required"}
    if not secret:
        return {"state": "NEEDS CREDENTIALS", "reason": "Encrypted SSH credential required"}
    client = paramiko.SSHClient(); client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        kwargs = {"hostname": host, "port": int(node.get("ssh_port", 22)), "username": node["username"], "timeout": timeout, "banner_timeout": timeout, "auth_timeout": timeout}
        if node.get("auth_method", "key") == "password":
            kwargs["password"] = secret
        else:
            try:
                key = paramiko.RSAKey.from_private_key(__import__("io").StringIO(secret))
            except Exception as exc:
                return {"state": "NEEDS CREDENTIALS", "reason": f"Invalid private key: {exc}"}
            kwargs["pkey"] = key
        client.connect(**kwargs)
        command = "uname -s; uname -m; getconf _NPROCESSORS_ONLN; awk '/MemTotal/ {print $2}' /proc/meminfo; df -Pk / | tail -1; command -v docker || true; python3 --version 2>/dev/null || true; node --version 2>/dev/null || true"
        _, stdout, _ = client.exec_command(command, timeout=timeout)
        lines = [line.strip() for line in stdout.read().decode("utf-8", "replace").splitlines()]
        return {"state": "AUTHENTICATED", "capabilities": {"os": lines[0] if len(lines)>0 else "", "architecture": lines[1] if len(lines)>1 else "", "cpuCores": lines[2] if len(lines)>2 else "", "ramKb": lines[3] if len(lines)>3 else "", "disk": lines[4] if len(lines)>4 else "", "docker": bool(lines[5]) if len(lines)>5 else False, "python": lines[6] if len(lines)>6 else "", "node": lines[7] if len(lines)>7 else ""}}
    except (paramiko.AuthenticationException, paramiko.BadAuthenticationType):
        return {"state": "AUTHENTICATION FAILED", "reason": "SSH authentication failed"}
    except (paramiko.SSHException, OSError, socket.timeout) as exc:
        return {"state": "OFFLINE", "reason": str(exc)[:160]}
    finally:
        client.close()


def test_node(node: Dict[str, Any], timeout: int = 5, secret: str = "") -> Dict[str, Any]:
    """Test connectivity without changing the node or running remote commands."""
    if not node.get("enabled"):
        return {"state": "OFFLINE", "reason": "Node disabled"}
    kind = node.get("connection_type")
    if kind == "local":
        caps = local_capabilities()
        return {"state": "ONLINE", "capabilities": caps}
    if kind == "agent":
        url = str(node.get("url") or node.get("hostname") or "").strip()
        protocol = str(node.get("agent_protocol") or "").lower()
        if protocol not in {"api", "websocket", "agent"}:
            return {"state": "UNSUPPORTED", "reason": "A real authenticated API, worker agent, or WebSocket terminal is required"}
        if not url.startswith(("https://", "http://", "wss://", "ws://")) or "sshx" in url.lower():
            return {"state": "UNSUPPORTED", "reason": "Normal webpages and sshx sharing links are not terminal interfaces"}
        if not secret:
            return {"state": "NEEDS CREDENTIALS", "reason": "Encrypted agent credential required"}
        return {"state": "NEEDS SETUP", "reason": "Authenticated agent adapter is not configured"}
    if kind == "ssh":
        if not secret:
            return {"state": "NEEDS CREDENTIALS", "reason": "Encrypted SSH credential required; TCP reachability is not authentication"}
        return test_ssh_node(node, secret, timeout=max(timeout, 8))
    return {"state": "UNSUPPORTED", "reason": "Unknown connection type"}
