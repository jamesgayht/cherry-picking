"""Timezone-aware clock. The user timezone comes from config/schedule.yaml, never a hardcoded offset."""
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.common.config import load_yaml


def now_local() -> datetime:
    return datetime.now(ZoneInfo(load_yaml("schedule.yaml")["timezone"]))
