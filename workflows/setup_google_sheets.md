# Setup: Google Sheets delivery

## Objective
Let `tools/delivery/sheets_append.py` append rows to your Google Sheet through a service account.

## Inputs
- A Google account and a Google Cloud project.
- The target spreadsheet; its id is the long string in its URL (`/spreadsheets/d/<id>/edit`), stored in `.env` as `GOOGLE_SHEETS_ID`.

## Tools
- `tools/delivery/sheets_append.py`

## Steps
1. In the Google Cloud console, enable the **Google Sheets API** for your project.
2. Create a service account (IAM & Admin → Service Accounts), add a JSON key, and save it as `credentials.json` at the repo root. It is gitignored; never commit it.
3. Set `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json` in `.env` (relative paths resolve against the repo root).
4. Open the sheet `GOOGLE_SHEETS_ID`, click **Share**, and add the key's `client_email` (`...@<project>.iam.gserviceaccount.com`) as **Editor**.
5. Verify:
   - Dry run (reads no secrets): `.venv/bin/python -m tools.delivery.sheets_append --tab Healthcheck --row '["phase0"]' --timestamp --dry-run`
   - Live append: `.venv/bin/python -m tools.delivery.sheets_append --tab Healthcheck --create-tab --timestamp --row '["phase0", "sheets_append works"]'`
   - Expect `{"ok": true, "tab": "Healthcheck", "rows": 1, "updated_range": "Healthcheck!A..."}` and a row with a `+08:00` timestamp.

## Outputs
- `credentials.json` at the repo root, `GOOGLE_SERVICE_ACCOUNT_FILE` and `GOOGLE_SHEETS_ID` in `.env`.
- A `Healthcheck` tab with one row.

## Edge cases
- Error "share it with … as Editor": step 4 was skipped, `GOOGLE_SHEETS_ID` is wrong, or the Sheets API isn't enabled (step 1). Google answers 403 for an unshared sheet and 404 for a wrong id; gspread 6 surfaces these as a bare `PermissionError` and `SpreadsheetNotFound`, and the tool maps both to this hint.
- Error "service account file not found": step 2 or 3 was skipped.
- Values are written RAW, so formulas (`=...`) are stored as text and never evaluated.
- Tab names are case-sensitive. A missing tab lists the available ones; pass `--create-tab` to create it.
- The planned tabs `Research`, `Signals`, `Backtests` and `Strategies` are created by their owning phases. Phase 0 only creates `Healthcheck`.
