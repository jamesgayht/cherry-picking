import json
import pytest
from tools.common import config
from tools.common import io as tio
from tools.common.log import get_logger

SECRET = "123456:SECRETSECRET"

@pytest.fixture
def secret_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"TELEGRAM_BOT_TOKEN={SECRET}\n")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", env)

def test_emit_writes_one_json_line_with_unicode(capsys):
    tio.emit({"ok": True, "text": "🟢 AAPL"})
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "🟢" in out
    assert json.loads(out) == {"ok": True, "text": "🟢 AAPL"}

def test_fail_prints_error_json_and_exits_1(capsys, secret_env):
    with pytest.raises(SystemExit) as exc:
        tio.fail("boom", tab="Signals")
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"error": "boom", "tab": "Signals"}

def test_run_emits_result_and_exits_0(capsys):
    with pytest.raises(SystemExit) as exc:
        tio.run(lambda: {"ok": True})
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}

def test_run_catches_exception_and_redacts(capsys, secret_env):
    def main():
        raise RuntimeError(f"POST https://api.telegram.org/bot{SECRET}/sendMessage")
    with pytest.raises(SystemExit) as exc:
        tio.run(main)
    assert exc.value.code == 1
    cap = capsys.readouterr()
    assert "SECRETSECRET" not in cap.out + cap.err
    assert json.loads(cap.out)["error"].startswith("RuntimeError: ")

def test_run_merges_exception_details(capsys, secret_env):
    class E(Exception):
        details = {"sent_message_ids": [1]}
    def main():
        raise E("partial")
    with pytest.raises(SystemExit):
        tio.run(main)
    assert json.loads(capsys.readouterr().out)["sent_message_ids"] == [1]

def test_argparse_errors_are_json_exit_2(capsys):
    p = tio.ArgumentParser(prog="x")
    p.add_argument("--tab", required=True)
    with pytest.raises(SystemExit) as exc:
        p.parse_args([])
    assert exc.value.code == 2
    assert "--tab" in json.loads(capsys.readouterr().out)["error"]

def test_logger_writes_stderr_and_redacts(capsys, secret_env):
    get_logger("t").error("token is %s", SECRET)
    cap = capsys.readouterr()
    assert cap.out == ""
    assert "SECRETSECRET" not in cap.err and "token is ***" in cap.err

def test_logger_has_single_handler():
    assert len(get_logger("dup").handlers) == len(get_logger("dup").handlers) == 1
