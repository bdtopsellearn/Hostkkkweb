from pathlib import Path
import tempfile
from ai_preflight import run_preflight
from sandbox_runtime import build_run_command
from vault_sync import sync_vault
import ai_preflight
import remote_worker
import sandbox_runtime
import security_scanner_free

# Report, but do not require, host Docker availability; live image pulls are avoided.
print("docker available:", sandbox_runtime.docker_available())

ROOT = Path(__file__).resolve().parent
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")

# Preflight rejects traversal and absolute entrypoints before invoking Docker.
tmp = Path(tempfile.mkdtemp())
(tmp / "main.py").write_text("print('ok')\n", encoding="utf-8")
assert run_preflight(tmp, "python", "../main.py")["verdict"] == "BLOCKED"
assert run_preflight(tmp, "python", "/etc/passwd")["verdict"] == "BLOCKED"

# Sandbox command construction must be containerized, read-only, and non-privileged.
cmd = build_run_command("b1", tmp, "main.py", "free", network=False, runtime="python", env_file=tmp / ".env")
joined = " ".join(map(str, cmd))
for required in ("--read-only", "--cap-drop", "ALL", "--network", "none"):
    assert required in joined, joined
assert "--privileged" not in cmd

# Plan limits are present in every generated sandbox command.
for plan, memory in (("free", "256m"), ("basic", "512m"), ("pro", "1g"), ("ultra", "2g")):
    generated = build_run_command("b1", tmp, "main.py", plan, network=False, runtime="python", env_file=None)
    assert memory in " ".join(generated)

# SSH input validation rejects incomplete nodes before any network attempt.
assert remote_worker.deploy({}, "secret", "b1", tmp, "python", "main.py", "free", {})["ok"] is False
assert remote_worker.deploy({"hostname": "127.0.0.1", "username": "u"}, "secret", "b1", tmp, "python", "main.py", "free", {})["ok"] is False

# Pre-flight timeout is deterministic when its subprocess is replaced by a sleeper.
class TimeoutProcess:
    def run(self, *args, **kwargs):
        raise __import__("subprocess").TimeoutExpired(kwargs.get("args", args[0] if args else "docker"), 1)
old_run = ai_preflight.subprocess.run
try:
    ai_preflight.subprocess.run = TimeoutProcess().run
    assert ai_preflight.run_preflight(tmp, "python", "main.py")["verdict"] == "BLOCKED"
finally:
    ai_preflight.subprocess.run = old_run

# Source invariants protect the approval gate, rollback path, and webhook secret check.
for marker in ("approval_status"):
    assert marker in BOT
assert "def _start_failure" in BOT
assert "deployment_rollback_at" in BOT
assert "compare_digest(supplied_secret, WEBHOOK_SECRET)" in BOT
assert "SANDBOX_TEST_TTL_SECONDS = 60" in BOT
assert 'threading.Timer(SANDBOX_TEST_TTL_SECONDS, _expire_sandbox_run' in BOT
assert 'remote_control(node or {}, _node_secret(info.get("node_id", "")), bot_id, "cleanup")' in BOT
assert '"cleanup"' in (ROOT / "remote_worker.py").read_text(encoding="utf-8")
assert "adm_vault_token" in BOT
assert "await_vault_token" in BOT
assert "_store_vault_runtime_token" in BOT
assert "Authorization" in BOT
assert "CIPHER_VAULT_TOKEN" in BOT
assert "def _local_amount_to_usd" in BOT
assert "https://api.oxapay.com/v1/payment/invoice" in BOT
assert '"merchant_api_key": OXAPAY_KEY' in BOT
assert '"amount": float(usd_amount)' in BOT
assert 'def _create_oxapay_invoice(local_amount: float, currency_code: str' in BOT
assert '_local_amount_to_usd(local_amount, currency_code)' in BOT
assert 'return None\n\ndef _ai_vision_verify' in BOT
assert 'allowed_source_exts = {".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx"}' in BOT
assert 'AI diagnosis is temporarily unavailable.' in BOT
assert '"currency": "USD"' in BOT
assert '"callback_url"' in BOT
assert '"order_id"' in BOT
assert 'data.get("track_id")' in BOT
assert "open.er-api.com/v6/latest/USD" in BOT
assert '"currency": "USD"' in BOT
assert "final_price_local" in BOT
assert 'b.get("approval_status") == "approved"' in BOT
assert 'doc_db["trusted_execution"] = True' in BOT
assert "progress_cb" in BOT
assert "Analyzing {index}/{total_scan_files}" in BOT
assert 'fname.lower().endswith(".zip")' in BOT
assert "allowed_exts" in BOT
assert "raw[:128 * 1024]" in BOT
assert "AI File Analysis" in BOT
assert "Could not read file" in BOT
assert "File is empty or contains no readable text code." in BOT
assert "Connection to AI uplink lost." in BOT
assert "_LORD_CIPHER_BRAGS" in BOT
assert "ai_lord_cipher_brags_recent" in BOT
assert "never repeat the same brag consecutively" in BOT
assert "_append_lord_cipher_brag(clean_res, m.from_user.id)" in BOT
assert "operator_owned" in BOT
assert 'b["trusted_execution"] = True' in BOT
assert 'GIT_CONFIG_KEY_0' in BOT
assert "_download_gh_archive" in BOT
assert "default_branch" in BOT
assert "archive fallback failed" in BOT
assert 'scan.get("recommendation") == "MANUAL_REVIEW"' in BOT
assert "Sandbox mode auto-approves non-dangerous manual-review results" in BOT
assert "clone_needs_approval" in BOT
assert "not sandbox_on" in BOT
assert 'member.filename.replace("\\\\", "/")' in BOT

# Sandbox scanning must block high-confidence dynamic execution and must not
# treat an unavailable scanner as proof of safety.
dangerous = security_scanner_free.scan_code("import subprocess\nsubprocess.run(user_input, shell=True, input=user_input)\n", "main.py")
assert dangerous["recommendation"] == "REJECT"
assert "Security scanner unavailable" in BOT

# Vault refuses plaintext operation when the encryption key is absent/invalid.
vault_result = sync_vault(tmp, token="", repo="owner/private", key="")
assert vault_result["ok"] is False
assert "token" in vault_result["error"].lower()
vault_result = sync_vault(tmp, token="placeholder", repo="owner/private", key="")
assert vault_result["ok"] is False
assert "CIPHER_VAULT_KEY" in vault_result["error"]
print("isolated regression suite passed")
