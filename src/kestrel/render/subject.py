"""Generate the email subject line."""
from __future__ import annotations
from datetime import datetime
import zoneinfo


def make_subject(slot: str, run_date: datetime, tz_name: str = "Australia/Sydney") -> str:
    tz = zoneinfo.ZoneInfo(tz_name)
    local = run_date.astimezone(tz) if run_date.tzinfo else run_date.replace(tzinfo=tz)
    date_str = local.strftime("%a %d-%b-%y")
    kind = "Morning" if slot == "morning" else "Afternoon"
    return f"D&DI {kind} Brief {date_str} [Kestrel]"
