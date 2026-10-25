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
