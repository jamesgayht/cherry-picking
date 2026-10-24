from datetime import timedelta

import pytest

from tools.common import config
from tools.common.clock import now_local
from tools.common.config import ROOT, ConfigError, get_secret, load_yaml, redact


def test_root_points_at_repo():
    assert (ROOT / "CLAUDE.md").is_file()


def test_load_yaml_reads_real_schedule():
    assert load_yaml("schedule.yaml")["timezone"] == "Asia/Singapore"


def test_load_yaml_missing_file_names_it(tmp_path):
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_yaml("nope.yaml", config_dir=tmp_path)


def test_load_yaml_rejects_non_mapping(tmp_path):
    (tmp_path / "list.yaml").write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_yaml("list.yaml", config_dir=tmp_path)


def test_get_secret_strips_inline_comment(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=abc123456789         # from @BotFather\n")
    assert get_secret("TELEGRAM_BOT_TOKEN", env_file=env) == "abc123456789"


def test_get_secret_blank_value_counts_as_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("FINNHUB_API_KEY=          # comment only\n")
    with pytest.raises(ConfigError, match="FINNHUB_API_KEY"):
        get_secret("FINNHUB_API_KEY", env_file=env)


def test_get_secret_default_used_when_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    assert get_secret("GOOGLE_SERVICE_ACCOUNT_FILE", default="credentials.json",
                      env_file=tmp_path / "absent.env") == "credentials.json"


def test_process_env_overrides_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("X_KEY=fromfile123\n")
    monkeypatch.setenv("X_KEY", "fromenv456")
    assert get_secret("X_KEY", env_file=env) == "fromenv456"


def test_get_secret_uses_module_env_file_at_call_time(tmp_path, monkeypatch):
    monkeypatch.delenv("Y_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("Y_KEY=patched12345\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    assert get_secret("Y_KEY") == "patched12345"


def test_redact_masks_long_values_only(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123456:ABCdefGHIjkl\nSHORT=abc\n")
    out = redact("POST https://api.telegram.org/bot123456:ABCdefGHIjkl/sendMessage abc", env_file=env)
    assert "ABCdefGHIjkl" not in out
    assert "bot***/sendMessage" in out
    assert out.endswith(" abc")


def test_now_local_is_aware_singapore():
    dt = now_local()
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(hours=8)
