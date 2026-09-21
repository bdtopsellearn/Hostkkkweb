from __future__ import annotations

import tempfile
from pathlib import Path

from community_products import (
    award_for_event,
    create_product,
    developer_level,
    product_access,
    record_activity,
    rename_project_file,
)


def test_product_referral_slots_and_expiry():
    db = {}
    product = create_product(db, path="/tmp/product", filename="hosting_bot.py", description="Pro bot", category="pro", plan="pro", referral_cost=2, price=10, slots=30, access_days=30)
    user = {"_id": 7, "plan": "pro", "referrals": [1, 2]}
    ok, _, p = product_access(db, 7, product["id"], plan_active=lambda plan: True, referral_count=2)
    assert ok and p["slots_remaining"] == 29
    ok, _, _ = product_access(db, 7, product["id"], plan_active=lambda plan: False, referral_count=2)
    assert not ok
    assert award_for_event(db, user, "referral") == ["first_referral"]
    record_activity(db, 7, "test", "safe public event")
    assert developer_level(user["xp"]) == "Code Apprentice"


def test_product_purchase_reuses_access_without_consuming_second_slot():
    db = {}
    product = create_product(db, path="/tmp/product", filename="bot.py", description="Paid", category="paid", plan="free", referral_cost=0, price=5, slots=3, access_days=30)
    ok, _, p = product_access(db, 9, product["id"], plan_active=lambda plan: True, purchase=True)
    assert ok and p["slots_remaining"] == 2
    ok, _, p = product_access(db, 9, product["id"], plan_active=lambda plan: True, purchase=True)
    assert ok and p["slots_remaining"] == 2


def test_purchase_can_unlock_higher_plan_but_referral_cannot():
    db = {}
    product = create_product(db, path="/tmp/product", filename="lifetime.py", description="Lifetime", category="lifetime", plan="lifetime", referral_cost=1, price=25, slots=2, access_days=30)
    ok, message, _ = product_access(db, 10, product["id"], plan_active=lambda _plan: False, referral_count=5)
    assert not ok and "lifetime plan" in message
    ok, _, purchased = product_access(db, 10, product["id"], plan_active=lambda _plan: False, purchase=True)
    assert ok and purchased["buyers"]["10"]["mode"] == "purchase"


def test_safe_rename_updates_text_references_and_rejects_traversal():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "old.py").write_text("print('ok')")
        (root / "Procfile").write_text("worker: python old.py")
        ok, name = rename_project_file(root, "old.py", "new.py")
        assert ok and name == "new.py" and (root / "new.py").exists()
        assert "new.py" in (root / "Procfile").read_text()
        ok, _ = rename_project_file(root, "new.py", "../escape.py")
        assert not ok


if __name__ == "__main__":
    test_product_referral_slots_and_expiry()
    test_product_purchase_reuses_access_without_consuming_second_slot()
    test_purchase_can_unlock_higher_plan_but_referral_cannot()
    test_safe_rename_updates_text_references_and_rejects_traversal()
    print("community product tests passed")
