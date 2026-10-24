"""The tool I/O contract: one JSON line on stdout, logs on stderr, non-zero exit with {"error": ...}."""
import argparse
import json
import sys
import traceback
from collections.abc import Callable
from typing import NoReturn

from tools.common import config
from tools.common.log import get_logger

log = get_logger(__name__)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def fail(message: str, *, code: int = 1, **details) -> NoReturn:
    emit({"error": config.redact(message), **details})
    raise SystemExit(code)


def run(main: Callable[[], dict]) -> NoReturn:
    try:
        result = main()
    except Exception as e:
        # Log the formatted traceback as the message so the redact filter covers it.
        log.error("%s", traceback.format_exc())
        fail(f"{type(e).__name__}: {e}", **getattr(e, "details", {}))
    emit(result)
    raise SystemExit(0)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail(message, code=2)
