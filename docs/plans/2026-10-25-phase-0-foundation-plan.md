# Phase 0 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Python foundation (venv, `tools/common`) and the two delivery tools, so a test message reaches Telegram and a test row reaches Google Sheets.

**Architecture:** `tools/common` holds the shared contract: config and secrets loading, secret redaction, stderr logging, and JSON stdout/exit-code handling. `tools/delivery/telegram_send.py` and `tools/delivery/sheets_append.py` are thin CLIs over pure, injectable functions (an HTTP session or a gspread client is passed in), so every behavior is unit-tested with fakes and no network access. Tools run as modules: `.venv/bin/python -m tools.delivery.telegram_send ...`.

**Tech Stack:** Python 3.14 (`/opt/homebrew/bin/python3.14`, pinned in `.python-version`), python-dotenv, PyYAML, requests, gspread 6 + google-auth (service account), pytest.

**Spec:** `docs/plans/2026-10-18-trading-bot-design.md` (§3 directory structure, §6 delivery formats, §8 safety, §9 Phase 0 row) and `CLAUDE.md` (Tool Contract, Safety Rules).

## Global Constraints

- Python 3.14 (pinned in `.python-version`), venv at `.venv/`, deps in `requirements.txt`. Before changing the version, confirm wheels exist for every dependency, including numba and vectorbt.
- Input from CLI args (argparse). Output is **JSON on stdout**, logs go to **stderr**, failures exit non-zero with JSON `{"error": ...}` on stdout. This includes argparse usage errors (exit 2).
- No hidden state. Config comes from `config/`, secrets from `.env` via `tools/common/config.py`.
- **Never print or log secrets.** Every error message and log line passes through `redact()`.
- Every tool has a test in `tests/`. Tests make no network calls.
- Timestamps are timezone-aware and use `timezone` from `config/schedule.yaml` (`Asia/Singapore`) via `zoneinfo`. Never hardcode offsets.
- Never place, modify, or cancel orders. Phase 0 touches no broker or market API.
- Don't commit `.env` or `credentials.json` (both already in `.gitignore`).
- Work on branch `phase-0-foundation`. Commit after each task.

## Review Focus

1. **A secret ends up in an error.** `requests` exceptions embed the URL, and the Telegram URL contains the bot token (`/bot<token>/sendMessage`). The token must never appear on stdout or stderr. Covered in Task 2 (`test_run_catches_exception_and_redacts`) and Task 3 (`test_connection_error_message_is_redacted_end_to_end`).
2. **Messages longer than Telegram's 4096-character limit.** These are sent as several messages split at newlines, with no text lost. Covered in Task 3 (`test_split_*`).
3. **Telegram rate limiting (HTTP 429, `retry_after`).** The tool waits `retry_after` and retries, up to 3 attempts, then fails cleanly. If a later chunk fails, the error reports which message ids were already sent. Covered in Task 3.
4. **Formula injection into Sheets.** Headlines or text starting with `=`, `+`, `-` or `@` are stored as literal text, never run as formulas. Covered in Task 4 (`test_append_rows_uses_raw_input`).
5. **The sheet isn't shared with the service account, or the tab doesn't exist.** The error says exactly what to do: share the sheet with `<client_email>` as Editor, or which tabs exist and how to use `--create-tab`. It shouldn't be a bare gspread traceback. Covered in Task 4.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | pytest config only (`pythonpath = ["."]`, `testpaths = ["tests"]`) |
| `requirements.txt` | modify: add pinned floors |
| `tools/__init__.py`, `tools/common/__init__.py`, `tools/delivery/__init__.py` | packages (empty) |
| `tools/common/config.py` | paths, YAML loading, secret lookup, redaction |
| `tools/common/clock.py` | `now_local()` in configured timezone |
| `tools/common/log.py` | stderr logger with redaction filter |
| `tools/common/io.py` | JSON stdout contract: `emit`, `fail`, `run`, `ArgumentParser` |
| `tools/delivery/telegram_send.py` | split + send Telegram messages |
| `tools/delivery/sheets_append.py` | append rows to a Sheets tab |
| `workflows/setup_telegram.md`, `workflows/setup_google_sheets.md` | setup procedures |
| `.env.example` | modify: add `GOOGLE_SERVICE_ACCOUNT_FILE`, `MARKETSTACK_API_KEY` (present in `.env`, missing from template) |
| `tests/test_config.py`, `tests/test_io_log.py`, `tests/test_telegram_send.py`, `tests/test_sheets_append.py` | tests (flat layout, unique basenames) |

---

### Task 1: Environment, config and clock

**Files:**
- Create: `pyproject.toml`, `tools/__init__.py`, `tools/common/__init__.py`, `tools/common/config.py`, `tools/common/clock.py`, `tests/test_config.py`
- Modify: `requirements.txt`, delete `tools/.gitkeep`

**Interfaces:**
- Produces:
  - `config.ROOT: Path` (repo root, `Path(__file__).resolve().parents[2]`), `config.CONFIG_DIR = ROOT / "config"`, `config.ENV_FILE = ROOT / ".env"`
  - `class ConfigError(Exception)`
  - `load_yaml(name: str, config_dir: Path | None = None) -> dict`. Uses `yaml.safe_load`. Raises `ConfigError` if the file is missing (message names the file) or the top level isn't a mapping.
  - `get_secret(name: str, default: str | None = None, env_file: Path | None = None) -> str`. A non-empty `os.environ[name]` wins, then the non-empty `.env` value (read with `dotenv_values`, which never mutates `os.environ`; a missing `.env` file counts as empty). Otherwise it returns `default` if given, or raises `ConfigError(f"missing secret {name}: set it in .env")`. The message holds the name, never a value.
  - `redact(text: str, env_file: Path | None = None) -> str`. Replaces every value of length ≥ 8 that appears in the `.env` file, or in `os.environ` under a key the `.env` file defines, with `***`. Longest values are replaced first.
  - `None` defaults resolve to the module attributes **at call time** (`config.ENV_FILE`, `config.CONFIG_DIR`), so tests can monkeypatch them.
  - `clock.now_local() -> datetime`: aware datetime in `load_yaml("schedule.yaml")["timezone"]`.

- [ ] **Step 1: Create the branch and venv**

```bash
git switch -c phase-0-foundation
/opt/homebrew/bin/python3.14 -m venv .venv
```
Set `requirements.txt` to:
```
python-dotenv>=1.0
pandas>=2.0
requests>=2.31
PyYAML>=6.0
gspread>=6.0
google-auth>=2.20
pytest>=8.0
```
Run: `.venv/bin/pip install -r requirements.txt`. Expected: it finishes with `Successfully installed ...`.

Create `pyproject.toml` with only `[tool.pytest.ini_options]`: `pythonpath = ["."]` and `testpaths = ["tests"]`. Create the empty `__init__.py` files and remove `tools/.gitkeep`.

- [ ] **Step 2: Write the failing tests in `tests/test_config.py`**

```python
from datetime import timedelta
import pytest
from tools.common import config
from tools.common.config import ConfigError, ROOT, get_secret, load_yaml, redact
from tools.common.clock import now_local


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
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.common.config'`.

- [ ] **Step 4: Implement `tools/common/config.py` and `tools/common/clock.py`**, using the Interfaces block above.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt tools/ tests/test_config.py
git commit -m "Add venv deps, pytest config, and tools/common config + clock"
```

---

### Task 2: Logging and the JSON I/O contract

**Files:**
- Create: `tools/common/log.py`, `tools/common/io.py`, `tests/test_io_log.py`

**Interfaces:**
- Consumes: `config.redact`, `config.ENV_FILE` (Task 1)
- Produces:
  - `get_logger(name: str) -> logging.Logger`. Logs to stderr with format `%(asctime)s %(levelname)s %(name)s: %(message)s` and level from env `LOG_LEVEL` (default `INFO`). A filter replaces `record.msg` with `redact(record.getMessage())` and clears `record.args`. The handler looks up `sys.stderr` **at emit time**, so pytest capture works. Calling it twice for the same name doesn't add a second handler, and `propagate=False`.
  - `emit(payload: dict) -> None`. Writes one line of `json.dumps(payload, ensure_ascii=False, default=str)` plus `\n` to stdout.
  - `fail(message: str, *, code: int = 1, **details) -> NoReturn`. Emits `{"error": redact(message), **details}` and raises `SystemExit(code)`.
  - `run(main: Callable[[], dict]) -> NoReturn`. Calls `main()`, emits the result, and exits 0. On any `Exception`, it logs the redacted traceback to stderr and calls `fail(f"{type(e).__name__}: {e}", **getattr(e, "details", {}))`. `SystemExit` passes through untouched.
  - `class ArgumentParser(argparse.ArgumentParser)`, whose `error(message)` calls `fail(message, code=2)`.

- [ ] **Step 1: Write the failing tests in `tests/test_io_log.py`**

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_io_log.py -v`
Expected: FAIL with `ModuleNotFoundError` for `tools.common.io` / `tools.common.log`.

- [ ] **Step 3: Implement `tools/common/log.py` and `tools/common/io.py`**, using the Interfaces block above.

- [ ] **Step 4: Run the full suite and confirm it passes**

Run: `.venv/bin/pytest -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/common/log.py tools/common/io.py tests/test_io_log.py
git commit -m "Add redacting stderr logger and JSON stdout/exit contract"
```

---

### Task 3: `telegram_send.py`

**Files:**
- Create: `tools/delivery/__init__.py`, `tools/delivery/telegram_send.py`, `tests/test_telegram_send.py`

**Interfaces:**
- Consumes: `get_secret` (Task 1); `ArgumentParser`, `run` (Task 2); `get_logger` (Task 2)
- Produces:
  - `TELEGRAM_LIMIT = 4096`, `API_URL = "https://api.telegram.org/bot{token}/sendMessage"`, `MAX_RETRY_AFTER = 60`
  - `class TelegramError(Exception)`, with `__init__(self, description: str, sent_message_ids: list[int])` and `self.details = {"sent_message_ids": sent_message_ids}`
  - `split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]`. Raises `ValueError` if `text.strip()` is empty. Each chunk is at most `limit`. A chunk breaks after the last `\n` within the limit, or hard-splits when a line has no `\n` inside the limit. The invariant is `"".join(chunks) == text`.
  - `send_message(text: str, *, token: str, chat_id: str, parse_mode: str | None = None, session=None, sleep=time.sleep, max_attempts: int = 3) -> list[int]`. It sends each chunk in order and returns the message ids. The POST JSON is `{"chat_id", "text", "disable_web_page_preview": True}`, plus `"parse_mode"` only when it's set, with `timeout=10`. Retry rules:
    - HTTP 429 with `parameters.retry_after ≤ 60`: `sleep(retry_after)`, then retry.
    - `requests.ConnectionError` or `requests.Timeout`: `sleep(2)`, then retry.
    - Any other `ok: false`: raise `TelegramError(description)` with no retry.
    - Retries run out, or `retry_after > 60`: raise `TelegramError`.
    - Every `TelegramError` carries the ids sent so far.
  - `main(argv: list[str] | None = None) -> dict`. Takes `--text TEXT` or `--stdin` (mutually exclusive, required), `--parse-mode {HTML,MarkdownV2}`, and `--dry-run`. A dry run returns `{"ok": True, "dry_run": True, "chunks": [...]}` without reading secrets. Otherwise it reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` and returns `{"ok": True, "chunks": n, "message_ids": [...]}`. The module ends with `if __name__ == "__main__": run(main)`.

- [ ] **Step 1: Write the failing tests in `tests/test_telegram_send.py`**

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_telegram_send.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.delivery'`.

- [ ] **Step 3: Implement `tools/delivery/telegram_send.py`**, using the Interfaces block above. When `session` is `None`, use `requests.Session()`. Import `time` at module level so the test can patch `tg.time.sleep`, and bind `sleep=None → time.sleep` at call time. Log each send attempt at INFO with the chunk index only, never the URL.

- [ ] **Step 4: Run the full suite and confirm it passes**

Run: `.venv/bin/pytest -v`
Expected: 34 passed.

- [ ] **Step 5: Run the CLI in dry-run mode**

Run: `.venv/bin/python -m tools.delivery.telegram_send --text "hello 🟢" --dry-run`
Expected stdout: `{"ok": true, "dry_run": true, "chunks": ["hello 🟢"]}`. Exit 0.
Run: `.venv/bin/python -m tools.delivery.telegram_send; echo "exit=$?"`
Expected: a JSON `{"error": "...one of the arguments --text --stdin is required"}` and `exit=2`.

- [ ] **Step 6: Commit**

```bash
git add tools/delivery/ tests/test_telegram_send.py
git commit -m "Add telegram_send tool with chunking, 429 retry, and redaction"
```

---

### Task 4: `sheets_append.py`

**Files:**
- Create: `tools/delivery/sheets_append.py`, `tests/test_sheets_append.py`

**Interfaces:**
- Consumes: `ROOT`, `ConfigError`, `get_secret` (Task 1); `now_local` (Task 1); `ArgumentParser`, `run`, `get_logger` (Task 2)
- Produces:
  - `parse_rows(raw: str) -> list[list]`. It accepts a JSON array of scalars (one row) or an array of arrays of scalars (many rows), and turns `null` into `""`. It raises `ValueError` for invalid JSON, a non-array top level, an empty outer array, an empty row, or any nested non-scalar.
  - `make_client(credentials_file: Path) -> gspread.Client`. Raises `ConfigError("service account file not found: <path> — see workflows/setup_google_sheets.md")` when the file is missing, and otherwise calls `gspread.service_account(filename=...)`.
  - `service_account_email(credentials_file: Path) -> str`. Returns `client_email` from the JSON key, or `"the service account"` if it can't be read.
  - `open_worksheet(client, sheet_id: str, tab: str, *, create: bool = False, account_email: str = "the service account")`. It maps `gspread.exceptions.SpreadsheetNotFound`, and `APIError` with status 403/404, to `ConfigError(f"cannot open the spreadsheet: share it with {account_email} as Editor (workflows/setup_google_sheets.md)")`. On `WorksheetNotFound` it adds the tab when `create` is set (`add_worksheet(title=tab, rows=1000, cols=26)`). Otherwise it raises `ConfigError(f"tab '{tab}' not found. Available tabs: A, B. Pass --create-tab to create it")`.
  - `append_rows(worksheet, rows: list[list]) -> dict`. Calls `worksheet.append_rows(rows, value_input_option="RAW")` and returns `{"rows": len(rows), "updated_range": resp["updates"]["updatedRange"]}`.
  - `main(argv: list[str] | None = None) -> dict` takes:
    - `--tab` (required)
    - exactly one of `--row JSON`, `--rows-file PATH`, `--stdin`
    - `--create-tab`
    - `--timestamp`, which prepends `now_local().isoformat(timespec="seconds")` to every row
    - `--dry-run`, which returns `{"ok": True, "dry_run": True, "tab": tab, "rows": rows}` without reading secrets

    A normal run reads `GOOGLE_SHEETS_ID` and `GOOGLE_SERVICE_ACCOUNT_FILE` (default `"credentials.json"`, relative paths resolved against `ROOT`) and returns `{"ok": True, "tab": tab, **append_rows(...)}`. The module ends with `if __name__ == "__main__": run(main)`.

- [ ] **Step 1: Write the failing tests in `tests/test_sheets_append.py`**

```python
import json
from datetime import datetime, timedelta
import gspread
import pytest
from tools.common import config
from tools.common.config import ConfigError
from tools.delivery import sheets_append as sa

class FakeWorksheet:
    def __init__(self, title):
        self.title, self.appended = title, []
    def append_rows(self, rows, value_input_option=None):
        self.appended.append((rows, value_input_option))
        return {"updates": {"updatedRange": f"{self.title}!A2:C{1 + len(rows)}"}}

class FakeSpreadsheet:
    def __init__(self, titles):
        self.sheets = {t: FakeWorksheet(t) for t in titles}
    def worksheet(self, title):
        if title not in self.sheets:
            raise gspread.exceptions.WorksheetNotFound(title)
        return self.sheets[title]
    def worksheets(self):
        return list(self.sheets.values())
    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]

class FakeClient:
    def __init__(self, spreadsheet=None, exc=None):
        self.spreadsheet, self.exc = spreadsheet, exc
    def open_by_key(self, key):
        if self.exc:
            raise self.exc
        return self.spreadsheet

@pytest.mark.parametrize("raw,expected", [
    ('["a", 1, null]', [["a", 1, ""]]),
    ('[["a"], ["b", 2.5, true]]', [["a"], ["b", 2.5, True]]),
])
def test_parse_rows_valid(raw, expected):
    assert sa.parse_rows(raw) == expected

@pytest.mark.parametrize("raw", ['{"a": 1}', "[]", "[[]]", '[["a", ["x"]]]', '[{"a": 1}]', "not json"])
def test_parse_rows_invalid(raw):
    with pytest.raises(ValueError):
        sa.parse_rows(raw)

def test_append_rows_uses_raw_input():
    ws = FakeWorksheet("Research")
    rows = [['=IMPORTXML("http://x","//a")', "+1", "-2", "@me"]]
    assert sa.append_rows(ws, rows) == {"rows": 1, "updated_range": "Research!A2:C2"}
    assert ws.appended == [(rows, "RAW")]

def test_open_worksheet_existing_tab():
    ss = FakeSpreadsheet(["Research", "Signals"])
    assert sa.open_worksheet(FakeClient(ss), "id", "Signals") is ss.sheets["Signals"]

def test_open_worksheet_missing_tab_lists_available():
    ss = FakeSpreadsheet(["Research", "Signals"])
    with pytest.raises(ConfigError, match=r"Available tabs: Research, Signals.*--create-tab"):
        sa.open_worksheet(FakeClient(ss), "id", "Healthcheck")

def test_open_worksheet_creates_tab_when_asked():
    ss = FakeSpreadsheet(["Research"])
    ws = sa.open_worksheet(FakeClient(ss), "id", "Healthcheck", create=True)
    assert ws.title == "Healthcheck" and "Healthcheck" in ss.sheets

def test_unshared_sheet_names_service_account():
    client = FakeClient(exc=gspread.exceptions.SpreadsheetNotFound())
    with pytest.raises(ConfigError, match="share it with bot@proj.iam.gserviceaccount.com as Editor"):
        sa.open_worksheet(client, "id", "Research", account_email="bot@proj.iam.gserviceaccount.com")

def test_make_client_missing_credentials_points_to_workflow(tmp_path):
    with pytest.raises(ConfigError, match="setup_google_sheets.md"):
        sa.make_client(tmp_path / "credentials.json")

def test_service_account_email_reads_key(tmp_path):
    key = tmp_path / "sa.json"
    key.write_text(json.dumps({"client_email": "bot@proj.iam.gserviceaccount.com"}))
    assert sa.service_account_email(key) == "bot@proj.iam.gserviceaccount.com"
    assert sa.service_account_email(tmp_path / "missing.json") == "the service account"

def test_dry_run_with_timestamp_needs_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "absent.env")
    for k in ("GOOGLE_SHEETS_ID", "GOOGLE_SERVICE_ACCOUNT_FILE"):
        monkeypatch.delenv(k, raising=False)
    out = sa.main(["--tab", "Healthcheck", "--row", '["hi"]', "--timestamp", "--dry-run"])
    assert out["ok"] and out["dry_run"] and out["tab"] == "Healthcheck"
    (ts, text), = out["rows"]
    assert text == "hi"
    assert datetime.fromisoformat(ts).utcoffset() == timedelta(hours=8)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_sheets_append.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError` for `tools.delivery.sheets_append`.

- [ ] **Step 3: Implement `tools/delivery/sheets_append.py`**, using the Interfaces block above.

- [ ] **Step 4: Run the full suite and confirm it passes**

Run: `.venv/bin/pytest -v`
Expected: 50 passed.

- [ ] **Step 5: Run the CLI in dry-run mode**

Run: `.venv/bin/python -m tools.delivery.sheets_append --tab Healthcheck --row '["=1+1"]' --timestamp --dry-run`
Expected stdout: `{"ok": true, "dry_run": true, "tab": "Healthcheck", "rows": [["2026-...+08:00", "=1+1"]]}`. Exit 0.

- [ ] **Step 6: Commit**

```bash
git add tools/delivery/sheets_append.py tests/test_sheets_append.py
git commit -m "Add sheets_append tool with RAW input and actionable access errors"
```

---

### Task 5: Setup workflows and the live end-to-end check (Phase 0 "done when")

This task includes **user actions**: creating the Google service account and sharing the sheet. Both live calls are free APIs, but they send a real Telegram message and write a real Sheets row, so confirm with the user before running them.

**Files:**
- Create: `workflows/setup_telegram.md`, `workflows/setup_google_sheets.md`
- Modify: `.env.example`, delete `workflows/.gitkeep`

**Interfaces:**
- Consumes: the CLIs from Tasks 3 and 4.

- [ ] **Step 1: Write `workflows/setup_telegram.md`**

Use the WAT workflow sections: Objective, Inputs, Tools, Steps, Outputs, Edge cases.
- **Steps:**
  1. Get a token from @BotFather and put it in `TELEGRAM_BOT_TOKEN`.
  2. Send `/start` to the bot.
  3. Find `chat.id` in `https://api.telegram.org/bot<token>/getUpdates`, opened in a browser and never pasted into chat or logs, and put it in `TELEGRAM_CHAT_ID`.
  4. Verify with a dry run, then with a live send.
- **Edge cases:**
  - A bot can't message a user who hasn't sent it `/start` (`403 Forbidden: bot can't initiate conversation`).
  - Group chat ids are negative.
  - Messages over 4096 characters are split at newlines.
  - With `--parse-mode HTML`, keep each tag on one line so a split can't break it.
  - A 429 is retried automatically.
  - A partial-send error lists `sent_message_ids`.

- [ ] **Step 2: Write `workflows/setup_google_sheets.md`**

- **Steps:**
  1. In a Google Cloud project, enable the **Google Sheets API**.
  2. Create a service account and download its JSON key to `credentials.json` at the repo root (it's gitignored).
  3. Set `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json` in `.env`.
  4. Open the sheet `GOOGLE_SHEETS_ID` and **Share** it with the key's `client_email` as **Editor**.
  5. Verify with a dry run, then a live append to `Healthcheck` with `--create-tab`.
- **Edge cases:**
  - Error "share it with … as Editor": step 4 was skipped.
  - Error "service account file not found": step 2 or 3 was skipped.
  - Values are written RAW, so formulas are never evaluated.
  - Tab names are case-sensitive.
  - The planned tabs `Research`, `Signals`, `Backtests` and `Strategies` are created by their owning phases. Phase 0 only creates `Healthcheck`.

- [ ] **Step 3: Update `.env.example`**

Add `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json   # path to service-account JSON key (gitignored)` under Delivery. Add `MARKETSTACK_API_KEY=   # optional; not used yet` under Research data.
Run: `git check-ignore credentials.json .env`
Expected: both paths are printed.

- [ ] **Step 4: User action.** Ask the user to finish workflow Steps 1–4 for Google Sheets and to confirm `TELEGRAM_*` is set. Wait for them to confirm.

- [ ] **Step 5: Live Telegram send** (after the user confirms)

Run: `.venv/bin/python -m tools.delivery.telegram_send --text "Phase 0 healthcheck ✅ telegram_send works. Alert only — not an order."`
Expected: `{"ok": true, "chunks": 1, "message_ids": [<int>]}`, exit 0, and the user confirms the message arrived in Telegram.

- [ ] **Step 6: Live Sheets append** (after the user confirms)

Run: `.venv/bin/python -m tools.delivery.sheets_append --tab Healthcheck --create-tab --timestamp --row '["phase0", "sheets_append works"]'`
Expected: `{"ok": true, "tab": "Healthcheck", "rows": 1, "updated_range": "Healthcheck!A..."}`, exit 0, and the user sees the row with an `+08:00` timestamp.

- [ ] **Step 7: Final verification**

Run: `.venv/bin/pytest -v && git status --short`
Expected: 50 passed. `git status` shows only the workflow and `.env.example` changes. `credentials.json` and `.env` aren't listed.

- [ ] **Step 8: Commit**

```bash
git rm workflows/.gitkeep
git add workflows/setup_telegram.md workflows/setup_google_sheets.md .env.example
git commit -m "Add Telegram and Google Sheets setup workflows; Phase 0 verified end to end"
```

---

## Out of scope for Phase 0 (deliberately)

- Tab headers and schemas for `Research`, `Signals`, `Backtests` and `Strategies` belong to Phases 1–3.
- The alert message format (§6) and the "Alert only — not an order" footer enforcement belong to Phase 3 (`scan.py`).
- Data tools, schedules and launchd belong to Phase 1 and later.
