from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC 'now'. The whole system stores naive UTC datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_dt(value) -> datetime | None:
    """Parse ISO-ish strings (with Z / offsets) into naive UTC. None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            dt = None
            for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%Y/%m/%d %H:%M"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
