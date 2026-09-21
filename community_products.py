"""Pure domain helpers for community rewards and admin-managed product files."""
from __future__ import annotations

import re
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEFAULT_ACHIEVEMENTS = {
    "first_upload": ("First Upload", "Uploaded your first bot", 10),
    "first_referral": ("Connector", "Referred your first user", 15),
    "five_referrals": ("Network Builder", "Reached five referrals", 40),
    "first_purchase": ("Collector", "Purchased your first product", 25),
    "seven_day_uptime": ("Steady Operator", "Maintained seven days of uptime", 75),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_after(days: int) -> str:
    return (utc_now() + timedelta(days=max(1, int(days)))).isoformat()


def ensure_db(db: Dict[str, Any]) -> Dict[str, Any]:
    db.setdefault("product_files", {})
    db.setdefault("activity_feed", [])
    db.setdefault("achievement_defs", {})
    return db


def record_activity(db: Dict[str, Any], uid: int, kind: str, message: str, public: bool = True) -> Dict[str, Any]:
    ensure_db(db)
    event = {"id": secrets.token_hex(8), "uid": int(uid), "kind": kind, "message": str(message)[:240], "public": bool(public), "ts": utc_now().isoformat()}
    db["activity_feed"].append(event)
    db["activity_feed"] = db["activity_feed"][-500:]
    return event


def award_for_event(db: Dict[str, Any], user: Dict[str, Any], event: str) -> list[str]:
    ensure_db(db)
    uid = str(user.get("_id", ""))
    unlocked = user.setdefault("achievements", [])
    refs = len(user.get("referrals", []) or [])
    rules = {"first_upload": event == "upload", "first_referral": refs >= 1, "five_referrals": refs >= 5, "first_purchase": event == "purchase", "seven_day_uptime": event == "uptime_7d"}
    new = []
    for key, qualifies in rules.items():
        if qualifies and key not in unlocked:
            unlocked.append(key); new.append(key)
    if new:
        user["xp"] = int(user.get("xp", 0)) + sum(DEFAULT_ACHIEVEMENTS[k][2] for k in new)
    return new


def developer_level(xp: int) -> str:
    xp = int(xp or 0)
    levels = [(500, "Cipher Architect"), (250, "Cyber Warden"), (100, "Runtime Engineer"), (40, "Bot Engineer"), (10, "Code Apprentice"), (0, "Script Initiate")]
    return next(name for threshold, name in levels if xp >= threshold)


def safe_filename(name: str, original: Optional[str] = None) -> str:
    raw_name = str(name or "").strip()
    if "/" in raw_name or "\\" in raw_name or raw_name in {".", ".."}:
        raise ValueError("Path components are not allowed in filenames.")
    name = Path(raw_name).name.strip()
    if not name or name in {".", ".."} or not SAFE_NAME_RE.fullmatch(name):
        raise ValueError("Invalid filename. Use letters, numbers, dots, underscores, or hyphens only.")
    if name.startswith(".") or name.lower() in {".env", "passwd", "shadow"}:
        raise ValueError("That filename is not allowed.")
    if original and Path(original).suffix.lower() != Path(name).suffix.lower():
        raise ValueError("The file extension cannot be changed during a rename.")
    return name


def rename_project_file(project_dir: str | Path, old_name: str, new_name: str) -> Tuple[bool, str]:
    root = Path(project_dir).resolve()
    try:
        old = safe_filename(old_name)
        new = safe_filename(new_name, old)
    except ValueError as exc:
        return False, str(exc)
    source = (root / old).resolve()
    target = (root / new).resolve()
    if root not in source.parents or root not in target.parents:
        return False, "Path escapes project directory"
    if not source.is_file():
        return False, "Original file was not found"
    if target.exists():
        return False, "A file with the new name already exists"
    source.rename(target)
    # Update only textual references; do not rewrite arbitrary binaries.
    for path in root.rglob("*"):
        if not path.is_file() or path in {source, target} or ".deps" in path.parts:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            updated = text.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return True, new


def create_product(db: Dict[str, Any], *, path: str, filename: str, description: str, category: str, plan: str, referral_cost: int, price: float, slots: int, access_days: int) -> Dict[str, Any]:
    ensure_db(db)
    pid = secrets.token_hex(8)
    product = {"id": pid, "path": path, "filename": safe_filename(filename), "description": str(description)[:1000], "category": str(category or "general")[:40], "plan": str(plan or "free"), "referral_cost": max(0, int(referral_cost)), "price": max(0.0, float(price)), "slot_limit": max(0, int(slots)), "slots_remaining": max(0, int(slots)), "access_days": max(1, int(access_days)), "buyers": {}, "referral_claims": {}, "created": utc_now().isoformat(), "active": True}
    db["product_files"][pid] = product
    return product


def product_access(db: Dict[str, Any], uid: int, product_id: str, *, plan_active, referral_count: int = 0, purchase: bool = False) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    ensure_db(db)
    p = db["product_files"].get(product_id)
    if not p or not p.get("active"):
        return False, "Product is unavailable", None
    key = str(uid)
    now = utc_now()
    # Referral unlocks require the user's active plan to meet the file's
    # minimum tier. A paid purchase is an explicit product entitlement and
    # may unlock a higher-tier file independently of the user's plan.
    if not purchase and p.get("plan") not in {"free", ""} and not plan_active(p.get("plan", "free")):
        return False, f"An active {p.get('plan')} plan is required", p
    existing = p.get("buyers", {}).get(key)
    if existing and datetime.fromisoformat(existing["expires"]) > now:
        return True, "Access granted", p
    if existing:
        return False, "Your access has expired", p
    if int(p.get("slots_remaining", 0)) <= 0:
        return False, "No access slots remain", p
    cost = int(p.get("referral_cost", 0))
    if not purchase and cost and int(referral_count) < cost:
        return False, f"You need {cost} referrals or purchase access", p
    p.setdefault("buyers", {})[key] = {"granted": now.isoformat(), "expires": iso_after(int(p.get("access_days", 30))), "mode": "purchase" if purchase else "referral"}
    if not purchase:
        p.setdefault("referral_claims", {})[key] = int(referral_count)
    p["slots_remaining"] = max(0, int(p.get("slots_remaining", 0)) - 1)
    return True, "Access granted", p
