"""Regression tests for live-monitor refresh stability."""
from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123456789:AA_test_token_for_monitor_tests")
os.environ.setdefault("OWNER_ID", "9001")

import bot  # noqa: E402


class Message:
    message_id = 77
    chat = type("Chat", (), {"id": 9001})()
    content_type = "photo"


class Call:
    message = Message()


old_running = bot.RUNNING
old_sessions = bot.LIVE_UI_SESSIONS
old_show_menu = bot.show_menu
try:
    # Remote entries do not have a local subprocess object. They must still be
    # renderable by the monitor refresh loop.
    bot.RUNNING = {
        "remote-1": {"remote": True, "node_status": "ONLINE", "name": "Remote Bot"},
    }
    bot.LIVE_UI_SESSIONS = {}
    rendered = []
    bot.show_menu = lambda *args, **kwargs: rendered.append((args, kwargs))
    bot.render_adm_live_monitor(Call())
    assert rendered, "monitor should render even with remote-only entries"
    assert bot.LIVE_UI_SESSIONS[9001]["type"] == "adm_monitor"

    # The source must keep refresh callbacks out of the generic admin fallback,
    # which previously made the refresh button appear to close the screen.
    source = open("bot.py", encoding="utf-8").read()
    for marker in (
        'if data == "adm_monitor_refresh":',
        'if data == "adm_monitor_bots":',
        'if data == "adm_monitor_system":',
        'def _is_running(info: Dict[str, Any]) -> bool:',
    ):
        assert marker in source, marker
finally:
    bot.RUNNING = old_running
    bot.LIVE_UI_SESSIONS = old_sessions
    bot.show_menu = old_show_menu

print("Monitor regression tests passed")
