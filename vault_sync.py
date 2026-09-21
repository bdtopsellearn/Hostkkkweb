"""Encrypted, versioned Cipher Vault synchronization for the hosting panel.

The engine creates a complete snapshot from the local storage and sandbox,
then publishes it to GitHub using the Git Data API: blobs -> tree -> commit ->
ref update. The ref is updated only after every blob and the manifest are
ready, so readers see either the previous complete snapshot or the new one.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import tarfile
import tempfile
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests
from cryptography.fernet import Fernet

EXCLUDES = {"node_modules", ".deps", ".tmp_run", "__pycache__", ".git", "logs"}
VAULT_SYNC_LOCK = threading.Lock()
REQUIRED_STATE_DIRS = ("storage", "sandbox")


def _safe_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & EXCLUDES:
            continue
        if path.suffix in {".pyc", ".log", ".tmp"}:
            continue
        yield path


def _archive(base_dir: Path) -> tuple[bytes, Dict[str, Any]]:
    """Build a deterministic compressed snapshot of restorable state."""
    buf = io.BytesIO()
    entries = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for dirname in ("storage", "sandbox"):
            root = base_dir / dirname
            for path in _iter_files(root):
                rel = f"{dirname}/{_safe_rel(path, root)}"
                info = tf.gettarinfo(str(path), arcname=rel)
                with path.open("rb") as fh:
                    tf.addfile(info, fh)
                raw = path.read_bytes()
                entries.append({"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    payload = buf.getvalue()
    return payload, {"files": entries, "fileCount": len(entries), "sizeBytes": len(payload)}


def _github(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            response = session.request(method, url, timeout=120, **kwargs)
            response.raise_for_status()
            return response
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_exc or RuntimeError("GitHub request failed")


def _api_base(repo: str) -> str:
    owner, name = repo.split("/", 1)
    return f"https://api.github.com/repos/{owner}/{name}"


def _sync_vault_unlocked(base_dir: str | Path, token: str, repo: str, branch: str = "main", key: str = "") -> Dict[str, Any]:
    """Create and atomically publish one encrypted snapshot to GitHub."""
    if not token or "/" not in repo:
        return {"ok": False, "error": "Vault token and owner/repository are required."}
    if not key:
        return {"ok": False, "error": "CIPHER_VAULT_KEY is required; refusing plaintext backup."}
    try:
        Fernet(key.encode()).encrypt(b"vault-key-check")
    except Exception as exc:
        return {"ok": False, "error": f"Invalid CIPHER_VAULT_KEY: {exc}"}

    base = Path(base_dir)
    missing = [name for name in REQUIRED_STATE_DIRS if not (base / name).is_dir()]
    if missing:
        return {"ok": False, "error": f"Required state directories missing: {', '.join(missing)}"}
    raw_archive, stats = _archive(base)
    if not stats.get("files"):
        return {"ok": False, "error": "Required state is empty; refusing to publish snapshot."}
    encrypted = Fernet(key.encode()).encrypt(raw_archive)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{now}-{hashlib.sha256(encrypted).hexdigest()[:12]}"
    manifest = {
        "format": "cipher-vault-v1",
        "snapshotId": snapshot_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "encrypted": True,
        "cipher": "Fernet",
        "archive": f"snapshots/{snapshot_id}/platform.tar.gz.enc",
        "archiveSha256": hashlib.sha256(encrypted).hexdigest(),
        **stats,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    api = _api_base(repo)
    try:
        ref = _github(session, "GET", f"{api}/git/ref/heads/{branch}").json()
        parent_sha = ref["object"]["sha"]
        parent_commit = _github(session, "GET", f"{api}/git/commits/{parent_sha}").json()
        base_tree = parent_commit["tree"]["sha"]

        def blob(data: bytes) -> str:
            return _github(session, "POST", f"{api}/git/blobs", json={
                "content": base64.b64encode(data).decode(), "encoding": "base64"
            }).json()["sha"]

        archive_sha = blob(encrypted)
        manifest["archiveBlobSha"] = archive_sha
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        manifest_sha = blob(manifest_bytes)
        latest_bytes = (json.dumps({"snapshotId": snapshot_id, "manifest": f"snapshots/{snapshot_id}/manifest.json"}, indent=2) + "\n").encode()
        latest_sha = blob(latest_bytes)
        tree = _github(session, "POST", f"{api}/git/trees", json={
            "base_tree": base_tree,
            "tree": [
                {"path": f"snapshots/{snapshot_id}/platform.tar.gz.enc", "mode": "100644", "type": "blob", "sha": archive_sha},
                {"path": f"snapshots/{snapshot_id}/manifest.json", "mode": "100644", "type": "blob", "sha": manifest_sha},
                {"path": "LATEST.json", "mode": "100644", "type": "blob", "sha": latest_sha},
            ],
        }).json()["sha"]
        commit = _github(session, "POST", f"{api}/git/commits", json={
            "message": f"vault: snapshot {snapshot_id}", "tree": tree, "parents": [parent_sha]
        }).json()["sha"]
        # The sole ref update is the atomic publication point.
        _github(session, "PATCH", f"{api}/git/refs/heads/{branch}", json={"sha": commit, "force": False})
        return {"ok": True, "snapshotId": snapshot_id, "commit": commit, "manifest": manifest}
    except requests.HTTPError as exc:
        return {"ok": False, "error": f"GitHub API error: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def sync_vault(base_dir: str | Path, token: str, repo: str, branch: str = "main", key: str = "") -> Dict[str, Any]:
    """Serialize concurrent syncs so a later job cannot race ref publication."""
    if not VAULT_SYNC_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "Another Cipher Vault sync is already in progress."}
    try:
        return _sync_vault_unlocked(base_dir, token, repo, branch, key)
    finally:
        VAULT_SYNC_LOCK.release()


def materialize_snapshot(base_dir: str | Path, encrypted_archive: bytes, key: str, overwrite: bool = False) -> Dict[str, Any]:
    """Validate/decrypt an archive into a staging directory, then replace state."""
    if not key:
        return {"ok": False, "error": "CIPHER_VAULT_KEY is required."}
    try:
        plain = Fernet(key.encode()).decrypt(encrypted_archive)
    except Exception as exc:
        return {"ok": False, "error": f"Backup authentication failed: {exc}"}
    base = Path(base_dir)
    stage = Path(tempfile.mkdtemp(prefix="cipher-vault-restore-", dir=str(base.parent)))
    try:
        with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tf:
            for member in tf.getmembers():
                target = (stage / member.name).resolve()
                if stage.resolve() not in target.parents:
                    return {"ok": False, "error": "Unsafe archive path."}
            tf.extractall(stage)
        if overwrite:
            backup = base.with_name(base.name + f".pre-restore-{int(time.time())}")
            if base.exists():
                base.rename(backup)
            stage.rename(base)
            return {"ok": True, "restoredFrom": str(backup)}
        return {"ok": True, "stagedAt": str(stage)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
