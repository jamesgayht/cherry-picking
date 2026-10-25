"""Append rows to a tab of the configured Google Sheet. Values are written RAW, never evaluated."""
import json
import sys
from pathlib import Path

import gspread

from tools.common.clock import now_local
from tools.common.config import ROOT, ConfigError, get_secret
from tools.common.io import ArgumentParser, run
from tools.common.log import get_logger

SETUP_WORKFLOW = "workflows/setup_google_sheets.md"
SCALARS = (str, int, float, bool)

log = get_logger(__name__)


def _parse_row(row) -> list:
    if not isinstance(row, list) or not row:
        raise ValueError("each row must be a non-empty JSON array")
    if any(v is not None and not isinstance(v, SCALARS) for v in row):
        raise ValueError("row values must be strings, numbers, booleans or null")
    return ["" if v is None else v for v in row]


def parse_rows(raw: str) -> list[list]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"rows are not valid JSON: {e}") from None
    if not isinstance(data, list) or not data:
        raise ValueError("rows must be a non-empty JSON array")
    if all(not isinstance(v, (list, dict)) for v in data):
        return [_parse_row(data)]
    return [_parse_row(row) for row in data]


def make_client(credentials_file: Path) -> gspread.Client:
    if not credentials_file.is_file():
        raise ConfigError(f"service account file not found: {credentials_file} — see {SETUP_WORKFLOW}")
    return gspread.service_account(filename=str(credentials_file))


def service_account_email(credentials_file: Path) -> str:
    try:
        key = json.loads(credentials_file.read_text())
        return key["client_email"]
    except (OSError, ValueError, KeyError, TypeError):
        return "the service account"


def open_worksheet(client, sheet_id: str, tab: str, *, create: bool = False,
                   account_email: str = "the service account"):
    no_access = ConfigError(f"cannot open the spreadsheet: share it with {account_email} as Editor ({SETUP_WORKFLOW})")
    try:
        spreadsheet = client.open_by_key(sheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        raise no_access from None
    except gspread.exceptions.APIError as e:
        if e.code in (403, 404):
            raise no_access from None
        raise
    try:
        return spreadsheet.worksheet(tab)
    except gspread.exceptions.WorksheetNotFound:
        if create:
            log.info("creating tab %s", tab)
            return spreadsheet.add_worksheet(title=tab, rows=1000, cols=26)
        available = ", ".join(ws.title for ws in spreadsheet.worksheets())
        raise ConfigError(f"tab '{tab}' not found. Available tabs: {available}. Pass --create-tab to create it") from None


def append_rows(worksheet, rows: list[list]) -> dict:
    resp = worksheet.append_rows(rows, value_input_option="RAW")
    return {"rows": len(rows), "updated_range": resp["updates"]["updatedRange"]}


def main(argv: list[str] | None = None) -> dict:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--tab", required=True, help="worksheet tab name (case-sensitive)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--row", help="JSON array (one row) or array of arrays (many rows)")
    source.add_argument("--rows-file", type=Path, help="file containing the rows JSON")
    source.add_argument("--stdin", action="store_true", help="read the rows JSON from stdin")
    parser.add_argument("--create-tab", action="store_true", help="create the tab if it does not exist")
    parser.add_argument("--timestamp", action="store_true", help="prepend the local time to every row")
    parser.add_argument("--dry-run", action="store_true", help="validate and print rows without writing")
    args = parser.parse_args(argv)

    if args.stdin:
        raw = sys.stdin.read()
    elif args.rows_file:
        raw = args.rows_file.read_text()
    else:
        raw = args.row
    rows = parse_rows(raw)
    if args.timestamp:
        ts = now_local().isoformat(timespec="seconds")
        rows = [[ts, *row] for row in rows]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "tab": args.tab, "rows": rows}

    credentials_file = Path(get_secret("GOOGLE_SERVICE_ACCOUNT_FILE", default="credentials.json"))
    if not credentials_file.is_absolute():
        credentials_file = ROOT / credentials_file
    worksheet = open_worksheet(make_client(credentials_file), get_secret("GOOGLE_SHEETS_ID"), args.tab,
                               create=args.create_tab, account_email=service_account_email(credentials_file))
    log.info("appending %d row(s) to %s", len(rows), args.tab)
    return {"ok": True, "tab": args.tab, **append_rows(worksheet, rows)}


if __name__ == "__main__":
    run(main)
