#!/usr/bin/env python3
"""Conservative static scanner for uploaded hosting projects.

The scanner is intentionally deterministic and review-oriented:
- normal Telegram, web, and package-management code is allowed;
- ambiguous findings produce MANUAL_REVIEW rather than an automatic block;
- only high-confidence combinations produce REJECT;
- Python AST checks are not applied to JavaScript, TypeScript, shell, or data files.
"""

from __future__ import annotations

import ast
import math
import os
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
try:
    from data_processor import DataProcessor
except ImportError:
    DataProcessor = None


# These patterns are deliberately narrow. Broad matches such as every use of
# requests, os.environ, sockets, or base64 create false positives in real bots.
PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "🔴 Restricted Access": [
        (r"os\.walk\s*\(\s*['\"]/(?:root|etc|home|proc|sys|var)(?:['\"]|/)",
         "Sensitive system directory traversal"),
        (r"glob\.glob\s*\(\s*['\"]/(?:\*)", "Broad system file search"),
        (r"shutil\.(?:copy|copy2|copyfile)\s*\([^\n]*['\"]/root(?:/|['\"])",
         "Copying from a restricted system path"),
        (r"(?:open|read_text)\s*\([^\n]*['\"]/(?:root|etc|proc|sys)[^\n]*\)[^\n]*(?:send_document|requests\.(?:post|put)|urllib)",
         "Sensitive file sent to an external destination"),
    ],
    "🔴 System Integrity": [
        (r"subprocess\s*\.\s*(?:Popen|call|run)\s*\([^\n]*shell\s*=\s*True[^\n]*(?:input|stdin)",
         "Shell command receives caller-controlled input"),
        (r"marshal\.loads\s*\(", "Loading executable marshalled data"),
        (r"base64\.b64decode\s*\([^\n]+\)[^\n]*\b(?:exec|eval)\b",
         "Decoded content is executed dynamically"),
        (r"zlib\.decompress\s*\([^\n]+\)[^\n]*\b(?:exec|eval)\b",
         "Compressed content is executed dynamically"),
    ],
    "🟡 Review Needed": [
        (r"\b(?:import\s+|from\s+)ctypes\b", "Low-level native module usage"),
        (r"\b(?:import\s+|from\s+)pickle\b", "Deserialization module usage"),
        (r"\bsocket\s*\.\s*socket\s*\(", "Raw socket usage"),
        (r"\b(?:import\s+|from\s+)marshal\b", "Bytecode serialization module usage"),
        (r"(?:base64\.b64decode|zlib\.decompress)\s*\(", "Encoded or compressed data handling"),
    ],
}

WEIGHTS: Dict[str, int] = {
    "🔴 Restricted Access": 45,
    "🔴 System Integrity": 45,
    "🟡 Review Needed": 8,
    "🔵 Info": 0,
}

BOT_TOKEN_RE = re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")
_CODE_SUFFIXES = {".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".sh"}
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".tar.gz"}


def _dedupe(values: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(str(v) for v in values if v))


def static_scan(code: str, filename: str = "") -> Dict[str, List[str]]:
    results: Dict[str, List[str]] = {}
    if filename and Path(filename).name == "security_scanner_free.py":
        return results

    for category, pattern_list in PATTERNS.items():
        hits: List[str] = []
        for pattern, description in pattern_list:
            try:
                if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                    hits.append(description)
            except re.error:
                continue
        if hits:
            results[category] = _dedupe(hits)

    # Bot tokens are expected in a hosting platform; they are not suspicious.
    tokens = BOT_TOKEN_RE.findall(code)
    if tokens:
        results.setdefault("🔵 Info", [])
        results["🔵 Info"].append(
            f"Bot token detected (ending in ...{tokens[0][-4:]})"
        )
    return results


def _python_ast_scan(code: str) -> List[str]:
    """Return AST findings only for Python source."""
    findings: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Python syntax error: {exc.msg} at line {exc.lineno}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if len(value) > 200:
                probabilities = [float(value.count(c)) / len(value) for c in set(value)]
                entropy = -sum(p * math.log(p, 2) for p in probabilities if p)
                if entropy > 5.3:
                    findings.append(
                        f"Large encoded configuration block detected (entropy={entropy:.2f})"
                    )

        if not isinstance(node, ast.Call):
            continue
        func = node.func

        if isinstance(func, ast.Attribute):
            if func.attr == "walk" and isinstance(func.value, ast.Name) and func.value.id == "os":
                if node.args and isinstance(node.args[0], ast.Constant):
                    path = node.args[0].value
                    if path in {"/", "/root", "/etc", "/home", "/proc", "/sys", "/var"}:
                        findings.append(f"Sensitive directory traversal: os.walk({path!r})")

            if func.attr == "system" and isinstance(func.value, ast.Name) and func.value.id == "os":
                if node.args and not isinstance(node.args[0], ast.Constant):
                    findings.append("HIGH_CONFIDENCE: os.system receives dynamic input")
                else:
                    findings.append("Shell command execution requires review")

            if func.attr in {"run", "call", "Popen"} and isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                shell_true = any(
                    kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                    for kw in node.keywords
                )
                has_dynamic_arg = bool(node.args) and not isinstance(node.args[0], ast.Constant)
                if shell_true and has_dynamic_arg:
                    findings.append("HIGH_CONFIDENCE: subprocess shell command receives dynamic input")
                elif shell_true:
                    findings.append("Shell command execution requires review")

            if func.attr in {"post", "put", "request"} and isinstance(func.value, ast.Name) and func.value.id in {"requests", "urllib"}:
                sensitive_file = any(
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in {"open", "read_text"}
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                    and sub.args[0].value.startswith(("/etc/", "/proc/", "/sys/", "/root/"))
                    for arg in list(node.args) + [kw.value for kw in node.keywords]
                    for sub in ast.walk(arg)
                )
                if sensitive_file:
                    findings.append("CRITICAL_CONFIDENCE: sensitive system file included in a network request")
                elif any(isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                         and sub.value.id == "os" and sub.attr == "environ"
                         for arg in list(node.args) + [kw.value for kw in node.keywords]
                         for sub in ast.walk(arg)):
                    findings.append("Environment data is included in a network request")

        if isinstance(func, ast.Name):
            if func.id in {"eval", "exec"} and node.args:
                argument = node.args[0]
                if isinstance(argument, (ast.Call, ast.Attribute, ast.Subscript)):
                    findings.append(f"HIGH_CONFIDENCE: dynamic {func.id}() execution")
                else:
                    findings.append(f"{func.id}() usage requires review")

            if func.id == "getattr" and len(node.args) >= 2:
                first, second = node.args[0], node.args[1]
                if (isinstance(first, ast.Name) and first.id in {"os", "sys", "subprocess"}
                        and isinstance(second, ast.Constant)
                        and second.value in {"system", "popen", "exec", "spawn"}):
                    findings.append("HIGH_CONFIDENCE: dynamic system API lookup")

            if func.id == "__import__" and node.args and isinstance(node.args[0], ast.Constant):
                if node.args[0].value in {"os", "subprocess", "ctypes", "sys"}:
                    findings.append("Dynamic system-module import requires review")

    return _dedupe(findings)


def ast_scan(code: str, filename: str = "") -> List[str]:
    suffix = Path(filename).suffix.lower()
    return _python_ast_scan(code) if suffix in {".py", ".pyw"} else []


def calculate_risk(static_findings: Dict[str, List[str]], ast_findings: List[str]) -> int:
    score = sum(
        WEIGHTS.get(category, 5) * min(len(hits), 3)
        for category, hits in static_findings.items()
        if hits
    )
    for finding in _dedupe(ast_findings):
        score += 60 if finding.startswith("CRITICAL_CONFIDENCE:") else (45 if finding.startswith("HIGH_CONFIDENCE:") else 8)
    return min(score, 100)


def _has_high_confidence_finding(static_findings: Dict[str, List[str]], ast_findings: List[str]) -> bool:
    high_confidence_phrases = (
        "external destination",
        "caller-controlled input",
        "executed dynamically",
    )
    return any(
        any(phrase in hit.lower() for phrase in high_confidence_phrases)
        for hits in static_findings.values() for hit in hits
    ) or any(finding.startswith(("HIGH_CONFIDENCE:", "CRITICAL_CONFIDENCE:")) for finding in ast_findings)


def _result(
    verdict: str,
    risk_score: int,
    findings: Dict[str, List[str]],
    ast_findings: List[str],
    filename: str,
) -> Dict[str, Any]:
    threats = _dedupe(
        [f"{category}: {hit}" for category, hits in findings.items() for hit in hits]
        + list(ast_findings)
    )
    if verdict == "DANGEROUS":
        summary = "High-confidence dangerous behavior detected."
    elif verdict == "SUSPICIOUS":
        summary = "Potentially risky behavior found; manual review is required."
    else:
        summary = "No high-confidence dangerous behavior found."
    return {
        "verdict": verdict,
        "risk_score": risk_score,
        "findings": findings,
        "ast_findings": ast_findings,
        "all_threats": threats,
        "recommendation": "REJECT" if verdict == "DANGEROUS" else (
            "MANUAL_REVIEW" if verdict == "SUSPICIOUS" else "APPROVE"
        ),
        "summary": summary,
        "filename": filename,
        "decoded_content": None,
    }


def scan_code(code: str, filename: str = "unknown.py") -> Dict[str, Any]:
    # Try to decode obfuscated content first
    decoded_content = None
    if DataProcessor and filename.lower().endswith(('.py', '.pyw')):
        processor = DataProcessor(depth=20)
        decoded, methods = processor.process(code)
        if methods:
            decoded_content = decoded
            # Scan the decoded content too
            code = code + "\n\n# --- DECODED CONTENT ---\n" + decoded

    findings = static_scan(code, filename)
    ast_findings = ast_scan(code, filename)
    risk = calculate_risk(findings, ast_findings)
    
    # If decoding found something, increase risk
    if decoded_content:
        risk = min(100, risk + 20)
        findings.setdefault("🟡 Review Needed", [])
        findings["🟡 Review Needed"].append("Obfuscated/Encoded payload decoded for inspection")

    high_confidence = _has_high_confidence_finding(findings, ast_findings)

    # Ignore "🔵 Info" when determining if a project is suspicious.
    suspicious_static = {k: v for k, v in findings.items() if not k.startswith("🔵")}

    # One warning is not enough to block a project. Automatic rejection requires
    # multiple points of evidence, including at least one high-confidence signal.
    critical = any(finding.startswith("CRITICAL_CONFIDENCE:") for finding in ast_findings)
    if critical or (high_confidence and risk >= 70):
        verdict = "DANGEROUS"
    elif suspicious_static or ast_findings or risk >= 20:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"
    return _result(verdict, risk, findings, ast_findings, filename)


def _safe_archive_member(name: str) -> bool:
    path = Path(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def _worst(results: Iterable[Dict[str, Any]], filename: str) -> Dict[str, Any]:
    values = list(results)
    if not values:
        return _result("SAFE", 0, {}, [], filename)
    return max(values, key=lambda item: int(item.get("risk_score", 0)))


def _scan_archive(filepath: str) -> Dict[str, Any]:
    suffix = filepath.lower()
    results: List[Dict[str, Any]] = []
    try:
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(filepath) as archive:
                for member in archive.infolist():
                    if not _safe_archive_member(member.filename):
                        return {
                            "verdict": "DANGEROUS",
                            "risk_score": 100,
                            "findings": {"🔴 Archive Safety": ["Unsafe archive path detected"]},
                            "ast_findings": [],
                            "all_threats": ["Unsafe archive path detected"],
                            "recommendation": "REJECT",
                            "summary": "Unsafe archive path detected.",
                            "filename": os.path.basename(filepath),
                            "decoded_content": None,
                        }
                    if not member.is_dir() and Path(member.filename).suffix.lower() in _CODE_SUFFIXES:
                        results.append(scan_code(archive.read(member).decode("utf-8", "ignore"), member.filename))
        else:
            with tarfile.open(filepath, "r:*") as archive:
                for member in archive.getmembers():
                    if not _safe_archive_member(member.name) or member.issym() or member.islnk():
                        return {
                            "verdict": "DANGEROUS",
                            "risk_score": 100,
                            "findings": {"🔴 Archive Safety": ["Unsafe archive member detected"]},
                            "ast_findings": [],
                            "all_threats": ["Unsafe archive member detected"],
                            "recommendation": "REJECT",
                            "summary": "Unsafe archive member detected.",
                            "filename": os.path.basename(filepath),
                            "decoded_content": None,
                        }
                    if member.isfile() and Path(member.name).suffix.lower() in _CODE_SUFFIXES:
                        stream = archive.extractfile(member)
                        if stream:
                            results.append(scan_code(stream.read().decode("utf-8", "ignore"), member.name))
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return {
            "verdict": "SUSPICIOUS",
            "risk_score": 20,
            "findings": {"🟡 Review Needed": [f"Archive could not be fully inspected: {exc}"]},
            "ast_findings": [],
            "all_threats": [f"Archive could not be fully inspected: {exc}"],
            "recommendation": "MANUAL_REVIEW",
            "summary": "Archive requires manual review.",
            "filename": os.path.basename(filepath),
            "decoded_content": None,
        }
    return _worst(results, os.path.basename(filepath))


def scan_file(filepath: str) -> Dict[str, Any]:
    try:
        lower = filepath.lower()
        if any(lower.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES):
            return _scan_archive(filepath)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
            return scan_code(handle.read(), os.path.basename(filepath))
    except OSError as exc:
        return {
            "verdict": "SUSPICIOUS",
            "risk_score": 20,
            "findings": {"🟡 Review Needed": [f"File could not be inspected: {exc}"]},
            "ast_findings": [],
            "all_threats": [f"File could not be inspected: {exc}"],
            "recommendation": "MANUAL_REVIEW",
            "summary": "File requires manual review.",
            "filename": os.path.basename(filepath),
            "decoded_content": None,
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 security_scanner_free.py <file>")
    result = scan_file(sys.argv[1])
    print(f"Scan Result for {sys.argv[1]}: {result['verdict']} ({result['risk_score']}/100)")
    for threat in result.get("all_threats", []):
        print(f" - {threat}")
