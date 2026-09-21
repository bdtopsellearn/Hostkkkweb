"""Restricted source preflight for hosted bots.

Preflight is fail-closed: syntax and behavioral checks run in disposable,
network-isolated containers. AI callers may use this module asynchronously and
must never apply a fix automatically.
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

_PATTERNS = {
    "network": re.compile(r"(?:socket|requests|urllib|httpx|aiohttp|fetch\s*\(|axios|curl|wget)", re.I),
    "filesystem": re.compile(r"(?:open\s*\(|pathlib|os\.(?:walk|listdir|remove|unlink)|shutil\.(?:rmtree|copy))", re.I),
    "subprocess": re.compile(r"(?:subprocess|os\.system|os\.popen|child_process|exec\s*\()", re.I),
    "transfer": re.compile(r"(?:send_document|send_file|upload|base64|webhook|telegram|discord|exfil|requests\.(?:post|put))", re.I),
}

def _source_findings(root: Path) -> Dict[str, list[str]]:
    findings: Dict[str, list[str]] = {key: [] for key in _PATTERNS}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".js", ".ts"}:
            continue
        if any(part in {".git", "__pycache__", ".deps", ".tmp_run"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for category, pattern in _PATTERNS.items():
            if pattern.search(text):
                findings[category].append(str(path.relative_to(root)))
    return findings

def run_preflight(bot_dir: str | Path, runtime: str, entry: str, timeout: int = 90) -> Dict[str, Any]:
    root = Path(bot_dir).resolve()
    entry_path = Path(entry)
    if not root.exists() or entry_path.is_absolute() or ".." in entry_path.parts:
        return {"ok": False, "verdict": "BLOCKED", "reason": "unsafe source path"}
    if runtime not in {"python", "node"} or not (root / entry_path).is_file():
        return {"ok": False, "verdict": "BLOCKED", "reason": "unsupported runtime or missing entrypoint"}
    findings = _source_findings(root)
    image = "node:22-slim" if runtime == "node" else "python:3.11-slim"
    syntax = ["node", "--check", f"/app/{entry}"] if runtime == "node" else ["python", "-m", "py_compile", f"/app/{entry}"]
    behavior = ["node", "--max-old-space-size=128", f"/app/{entry}"] if runtime == "node" else ["python", "-I", "-u", f"/app/{entry}"]
    common = ["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--pids-limit", "64", "--memory", "256m", "--cpus", "0.25", "--user", "65532:65532", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "-e", "CIPHER_PREFLIGHT=1", "-e", "BOT_TOKEN=preflight-invalid-token", "-v", f"{root}:/app:ro", "-w", "/app", image]
    try:
        checked = subprocess.run(common + syntax, capture_output=True, text=True, timeout=min(timeout, 90))
    except FileNotFoundError:
        return {"ok": False, "verdict": "NEEDS SETUP", "reason": "Docker unavailable", "findings": findings}
    except subprocess.TimeoutExpired:
        return {"ok": False, "verdict": "BLOCKED", "reason": "syntax preflight timed out", "findings": findings}
    if checked.returncode != 0:
        return {"ok": False, "verdict": "DANGEROUS", "reason": "syntax check failed", "stderr": checked.stderr[-2000:], "findings": findings}
    try:
        observed = subprocess.run(common + behavior, capture_output=True, text=True, timeout=min(timeout, 15))
    except subprocess.TimeoutExpired:
        return {"ok": False, "verdict": "BLOCKED", "reason": "behavioral preflight timed out", "findings": findings}
    except FileNotFoundError:
        return {"ok": False, "verdict": "NEEDS SETUP", "reason": "Docker unavailable", "findings": findings}
    if observed.returncode not in {0, 1, 2} and not observed.stdout and not observed.stderr:
        return {"ok": False, "verdict": "DANGEROUS", "reason": "behavioral check failed", "findings": findings}
    risky = [category for category, files in findings.items() if files]
    return {"ok": not risky, "verdict": "REVIEW" if risky else "SAFE", "reason": "manual review required for detected capabilities" if risky else "restricted checks passed", "findings": findings, "stdout": observed.stdout[-2000:], "stderr": observed.stderr[-2000:]}
