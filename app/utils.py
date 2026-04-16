"""Shared utility helpers used across route modules."""
import re

_MONTH_KEY_RE = re.compile(r"^\d{4}-\d{2}$")


def split_tags(tags_value):
    """Split a comma-separated tag string into a list of stripped, non-empty tags."""
    return [tag.strip() for tag in (tags_value or "").split(",") if tag.strip()]


def optional_float(value, default=None, divide_by_100=False, min_val=None):
    """Parse a string or numeric value to float, returning `default` on failure."""
    value = (str(value) if value is not None else "").strip()
    if value == "":
        return default
    try:
        result = float(value)
    except (ValueError, TypeError):
        return default
    if divide_by_100:
        result = result / 100.0
    if min_val is not None:
        result = max(min_val, result)
    return result


def optional_int(value, default=None):
    """Parse a string or numeric value to int, returning `default` on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_month_key(raw):
    """Return the YYYY-MM portion of raw if it looks valid, else None."""
    s = (raw or "")[:7]
    return s if _MONTH_KEY_RE.match(s) else None
