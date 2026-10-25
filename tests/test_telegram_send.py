import json
import pytest
import requests
from tools.common import config
from tools.common import io as tio
from tools.delivery import telegram_send as tg
from tools.delivery.telegram_send import TelegramError, send_message, split_message

class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def json(self):
        return self.payload

class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

def ok(mid):
    return FakeResponse({"ok": True, "result": {"message_id": mid}})

def rate_limited(after):
    return FakeResponse({"ok": False, "error_code": 429, "description": "Too Many Requests",
                         "parameters": {"retry_after": after}}, status=429)

def send(session, text="hi", **kw):
    sleeps = []
    ids = send_message(text, token="TOKEN", chat_id="42", session=session, sleep=sleeps.append, **kw)
    return ids, sleeps

def test_split_short_text_is_one_chunk():
    assert split_message("hello") == ["hello"]

def test_split_breaks_on_newlines_without_losing_text():
    text = "".join(f"line {i:04d}\n" for i in range(500))   # 5000 chars
    chunks = split_message(text)
    assert len(chunks) == 2
    assert all(len(c) <= 4096 for c in chunks)
    assert chunks[0].endswith("\n")
    assert "".join(chunks) == text

def test_split_hard_splits_a_single_long_line():
    text = "x" * 9000
    chunks = split_message(text)
    assert [len(c) for c in chunks] == [4096, 4096, 808]
    assert "".join(chunks) == text

def test_split_rejects_blank():
    with pytest.raises(ValueError):
        split_message("  \n ")

def test_send_posts_expected_request():
    s = FakeSession([ok(1)])
    ids, _ = send(s)
    assert ids == [1]
    assert s.calls == [{"url": "https://api.telegram.org/botTOKEN/sendMessage",
                        "json": {"chat_id": "42", "text": "hi", "disable_web_page_preview": True},
                        "timeout": 10}]

def test_send_includes_parse_mode_when_set():
    s = FakeSession([ok(1)])
    send(s, text="<b>hi</b>", parse_mode="HTML")
    assert s.calls[0]["json"]["parse_mode"] == "HTML"

def test_long_message_sends_each_chunk_in_order():
    s = FakeSession([ok(1), ok(2)])
    ids, _ = send(s, text="a\n" * 3000)
    assert ids == [1, 2]
    assert "".join(c["json"]["text"] for c in s.calls) == "a\n" * 3000

def test_429_waits_retry_after_then_succeeds():
    ids, sleeps = send(FakeSession([rate_limited(3), ok(7)]))
    assert ids == [7] and sleeps == [3]

def test_429_with_huge_retry_after_fails_without_sleeping():
    with pytest.raises(TelegramError):
        send(FakeSession([rate_limited(600)]))

def test_429_exhausts_attempts():
    with pytest.raises(TelegramError):
        send(FakeSession([rate_limited(1)] * 3))

def test_connection_error_retries_after_2s():
    ids, sleeps = send(FakeSession([requests.ConnectionError("down"), ok(5)]))
    assert ids == [5] and sleeps == [2]

def test_bad_request_fails_immediately_with_description():
    s = FakeSession([FakeResponse({"ok": False, "error_code": 400,
                                   "description": "Bad Request: can't parse entities"}, 400)])
    with pytest.raises(TelegramError, match="can't parse entities"):
        send(s, parse_mode="HTML")
    assert len(s.calls) == 1

def test_partial_failure_reports_sent_ids():
    s = FakeSession([ok(1), FakeResponse({"ok": False, "error_code": 400, "description": "Bad"}, 400)])
    with pytest.raises(TelegramError) as exc:
        send(s, text="a\n" * 3000)
    assert exc.value.details == {"sent_message_ids": [1]}

def test_dry_run_needs_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "absent.env")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert tg.main(["--text", "hi", "--dry-run"]) == {"ok": True, "dry_run": True, "chunks": ["hi"]}

def test_connection_error_message_is_redacted_end_to_end(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=999999:LEAKYLEAKYLEAKY\nTELEGRAM_CHAT_ID=12345678\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    def boom(*a, **kw):
        raise requests.ConnectionError(
            "HTTPSConnectionPool: /bot999999:LEAKYLEAKYLEAKY/sendMessage")
    monkeypatch.setattr(requests.Session, "post", boom)
    monkeypatch.setattr(tg.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit) as exc:
        tio.run(lambda: tg.main(["--text", "hi"]))
    assert exc.value.code == 1
    cap = capsys.readouterr()
    assert "LEAKY" not in cap.out + cap.err
    assert "error" in json.loads(cap.out)

def test_split_counts_utf16_units_like_telegram():
    text = "🟢 ok\n" * 800                       # 4000 code points, 4800 UTF-16 units
    chunks = split_message(text)
    assert len(chunks) == 2
    assert all(len(c.encode("utf-16-le")) // 2 <= 4096 for c in chunks)
    assert "".join(chunks) == text

@pytest.mark.parametrize("text", ["x" * 4096 + "\n", "\n" + "x" * 5000, "x" * 4096 + "\n" * 5000 + "y"],
                         ids=["trailing-newline", "leading-newline", "newline-run"])
def test_split_never_yields_whitespace_only_chunks(text):
    chunks = split_message(text)
    assert all(c.strip() for c in chunks)
    assert "".join(chunks).split() == text.split()   # only whitespace Telegram would trim is dropped

def test_env_only_token_is_redacted_end_to_end(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=   # from @BotFather\n")
    monkeypatch.setattr(config, "ENV_FILE", env)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "888888:ENVONLYENVONLY")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345678")
    def boom(*a, **kw):
        raise requests.ConnectionError("HTTPSConnectionPool: /bot888888:ENVONLYENVONLY/sendMessage")
    monkeypatch.setattr(requests.Session, "post", boom)
    monkeypatch.setattr(tg.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        tio.run(lambda: tg.main(["--text", "hi"]))
    cap = capsys.readouterr()
    assert "ENVONLY" not in cap.out + cap.err
