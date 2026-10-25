"""Send a message to the configured Telegram chat. Splits long text, retries 429s and network errors."""
import sys
import time
from bisect import bisect_right
from itertools import accumulate

import requests

from tools.common.config import get_secret
from tools.common.io import ArgumentParser, run
from tools.common.log import get_logger

TELEGRAM_LIMIT = 4096
API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRY_AFTER = 60
NETWORK_RETRY_DELAY = 2

log = get_logger(__name__)


class TelegramError(Exception):
    def __init__(self, description: str, sent_message_ids: list[int]):
        super().__init__(description)
        self.details = {"sent_message_ids": sent_message_ids}


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into chunks of at most `limit` UTF-16 code units, the unit Telegram counts.

    Breaks after the last newline that fits, else hard-splits between code points. Whitespace-only
    chunks are dropped (Telegram trims them to empty and rejects them); all other text is kept.
    """
    if not text.strip():
        raise ValueError("message text is empty")
    # units[i] = UTF-16 length of text[:i]; characters outside the BMP (emoji) count as 2.
    units = [0, *accumulate(2 if ord(c) > 0xFFFF else 1 for c in text)]
    chunks, pos = [], 0
    while units[-1] - units[pos] > limit:
        fit = max(bisect_right(units, units[pos] + limit) - 1, pos + 1)
        newline = text.rfind("\n", pos + 1, fit)
        end = newline + 1 if newline != -1 else fit
        chunks.append(text[pos:end])
        pos = end
    chunks.append(text[pos:])
    return [c for c in chunks if c.strip()]


def _send_chunk(session, url: str, payload: dict, *, sleep, max_attempts: int, sent: list[int]) -> int:
    description = "no attempts made"
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.post(url, json=payload, timeout=10)
        except (requests.ConnectionError, requests.Timeout) as e:
            description = f"{type(e).__name__}: {e}"
            if attempt < max_attempts:
                sleep(NETWORK_RETRY_DELAY)
            continue
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(f"HTTP {response.status_code}: non-JSON response", sent) from None
        if body.get("ok"):
            return body["result"]["message_id"]
        description = body.get("description", f"HTTP {response.status_code}")
        if body.get("error_code") != 429:
            raise TelegramError(description, sent)
        retry_after = body.get("parameters", {}).get("retry_after", NETWORK_RETRY_DELAY)
        if retry_after > MAX_RETRY_AFTER:
            raise TelegramError(f"{description} (retry_after={retry_after}s exceeds {MAX_RETRY_AFTER}s)", sent)
        if attempt < max_attempts:
            sleep(retry_after)
    raise TelegramError(f"gave up after {max_attempts} attempts: {description}", sent)


def send_message(text: str, *, token: str, chat_id: str, parse_mode: str | None = None,
                 session=None, sleep=None, max_attempts: int = 3) -> list[int]:
    session = session or requests.Session()
    sleep = sleep or time.sleep
    url = API_URL.format(token=token)
    chunks = split_message(text)
    sent: list[int] = []
    for i, chunk in enumerate(chunks, 1):
        payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        log.info("sending chunk %d/%d", i, len(chunks))
        sent.append(_send_chunk(session, url, payload, sleep=sleep, max_attempts=max_attempts, sent=sent))
    return sent


def main(argv: list[str] | None = None) -> dict:
    parser = ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="message text")
    source.add_argument("--stdin", action="store_true", help="read message text from stdin")
    parser.add_argument("--parse-mode", choices=["HTML", "MarkdownV2"])
    parser.add_argument("--dry-run", action="store_true", help="split and print chunks without sending")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.stdin else args.text
    chunks = split_message(text)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "chunks": chunks}
    ids = send_message(text, token=get_secret("TELEGRAM_BOT_TOKEN"), chat_id=get_secret("TELEGRAM_CHAT_ID"),
                       parse_mode=args.parse_mode)
    return {"ok": True, "chunks": len(chunks), "message_ids": ids}


if __name__ == "__main__":
    run(main)
