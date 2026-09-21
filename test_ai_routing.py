"""Focused regression tests for plan-aware AI routing.

The bot module is imported with a fake Telegram token, then its persistence
functions are replaced with in-memory stores so the tests never touch live
settings or send network requests.
"""
from __future__ import annotations

import os
import copy
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "123456789:AA_test_token_for_routing_tests")
os.environ.setdefault("OWNER_ID", "9001")

import bot  # noqa: E402


settings = {}
users = {
    "42": {
        "id": 42,
        "plan": "lifetime",
        "plan_expires": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "ai_models": [],
    },
    "9001": {
        "id": 9001,
        "plan": "lifetime",
        "plan_expires": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "ai_models": [],
    },
}


def fake_settings_load():
    return dict(settings)


def fake_settings_load_ro():
    return settings


def fake_settings_save(value):
    settings.clear()
    settings.update(value)


def fake_db_load():
    return {"users": copy.deepcopy(users)}


def fake_db_load_ro():
    return {"users": users}


def fake_db_save(value):
    users.clear()
    users.update(value["users"])


bot.settings_load = fake_settings_load
bot.settings_load_ro = fake_settings_load_ro
bot.settings_save = fake_settings_save
bot.db_load = fake_db_load
bot.db_load_ro = fake_db_load_ro
bot.db_save = fake_db_save


all_models = list(bot._AI_OPERATIVE_KEYS)
assert len(all_models) > 3, "the fixture must exercise more than the old limit"
bot.set_plan_ai_models("lifetime", all_models)
assert settings["ai_plan_lifetime_models"] == all_models
assert bot.get_plan_ai_models("lifetime") == all_models

# An explicitly assigned paid plan is respected for an admin/owner too, so
# the admin can verify the same plan pool that ordinary users see.
assert bot.get_ai_model(42) == "lifetime"
assert bot.get_ai_model(9001) == "lifetime"

# No user-side three-model truncation remains, either for defaults or saved
# choices. A saved choice is preserved without deleting later fallbacks.
assert bot.get_user_ai_models(42, "lifetime") == all_models
bot.set_user_ai_models(42, all_models)
assert users["42"]["ai_models"] == all_models
assert bot.get_user_ai_models(42, "lifetime") == all_models

# The selected model is tried first, but the full plan pool remains in the
# chain rather than being sliced to three entries.
bot.USER_STATES[42] = {"ai_model": all_models[-1]}
called = []
bot._call_kaalix_model = lambda model, prompt: called.append(model) or None
reply, used = bot._call_ai_chain("test", "lifetime", 42)
assert reply is None and used is None
assert called[: len(all_models)] == [all_models[-1], *all_models[:-1]]

# The shared response boundary enforces the same relationship for every AI
# feature, not only the Telegram chat handler.
bot._call_ai_chain = lambda prompt, plan, uid=None: ("I am a general assistant.", "claude")
identity_reply = bot._call_ai_api("Who is your master and creator?", "lifetime", 42)
identity_lower = identity_reply.lower()
for term in ("lord cipher", "creator", "mentor", "master"):
    assert term in identity_lower, identity_reply

print("AI routing regression tests passed")
