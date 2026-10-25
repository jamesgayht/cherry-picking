# Setup: Telegram delivery

## Objective
Give `tools/delivery/telegram_send.py` a bot token and a chat id so alerts and briefs reach your Telegram.

## Inputs
- A Telegram account.
- `.env` (copied from `.env.example`).

## Tools
- `tools/delivery/telegram_send.py`

## Steps
1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. Put the token it gives you in `.env` as `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it `/start`.
3. Open `https://api.telegram.org/bot<token>/getUpdates` **in a browser** and find `result[].message.chat.id`. Put it in `.env` as `TELEGRAM_CHAT_ID`. Never paste the token or this URL into chat, logs, or commits.
4. Verify:
   - Dry run (reads no secrets): `.venv/bin/python -m tools.delivery.telegram_send --text "hello" --dry-run`
   - Live send: `.venv/bin/python -m tools.delivery.telegram_send --text "Phase 0 healthcheck ✅ telegram_send works. Alert only — not an order."`
   - Expect `{"ok": true, "chunks": 1, "message_ids": [...]}` and the message in Telegram.

## Outputs
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.
- One healthcheck message in the chat.

## Edge cases
- `403 Forbidden: bot can't initiate conversation`: a bot can't message a user who hasn't sent it `/start`. Do step 2.
- Group chat ids are negative (e.g. `-100...`). Keep the minus sign.
- Messages over 4096 characters are split at newlines and sent as several messages.
- With `--parse-mode HTML`, keep each tag on one line so a split can't break it.
- A 429 (rate limit) is retried automatically when `retry_after` ≤ 60s; longer waits fail.
- A partial-send error lists `sent_message_ids` — those chunks already arrived; don't resend blindly.
