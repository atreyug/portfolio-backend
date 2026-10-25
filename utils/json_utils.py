"""
Utility: JSON safety helpers.

Pandas / NumPy can produce NaN, NaT, inf, -inf.
FastAPI's JSON serialiser rejects these.

Use sanitize_for_json() on any dict/list/scalar before
returning it from an API endpoint.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def sanitize_value(value: Any) -> Any:
    """
    Convert a single value to a JSON-safe equivalent.

    NaN  → None
    inf  → None
    -inf → None
    NaT  → None
    datetime → ISO string
    date     → ISO string
    bytes    → str
    anything else → as-is
    """
    # None stays None
    if value is None:
        return None

    # pandas NaT / numpy NaT – check via string representation
    # (avoids importing pandas here)
    try:
        import pandas as pd  # type: ignore
        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass

    # floats: NaN / inf
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    # int, bool – safe
    if isinstance(value, (int, bool)):
        return value

    # datetime → ISO string
    if isinstance(value, datetime):
        return value.isoformat()

    # date → ISO string
    if isinstance(value, date):
        return value.isoformat()

    # bytes → str
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return str(value)

    return value


def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively walk *obj* (dict, list, scalar) and replace every
    JSON-unsafe value with its safe equivalent.

    Returns a new object of the same shape.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]

    if isinstance(obj, tuple):
        return tuple(sanitize_for_json(item) for item in obj)

    return sanitize_value(obj)
