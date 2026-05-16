"""
In-memory session cache.

PURPOSE:
    Avoids requiring the user to re-upload their file on every request.
    After /process parses the uploaded file (CSV/XLSX/XLS from the user's
    machine, e.g. 'Online Retail.xlsx'), the resulting Polars DataFrame is
    stored here under a UUID key.  Downstream endpoints (/analyze, /recommend,
    /ai/*) retrieve the DataFrame by session_id instead of re-reading the file.

CONTENTS PER SESSION:
    df           — the full parsed Polars DataFrame (all original columns)
    col_map      — canonical-name → actual-column-name mapping built by utils.resolve_columns()
    labels       — KMeans cluster label (int) per customer, filled after clustering
    customer_ids — list of CustomerID strings, parallel to `labels`
    ts           — Unix timestamp of last access, used for TTL eviction

TTL: 30 minutes, evicted lazily (checked on each write, not on a background timer).
"""
import time
import uuid
import polars as pl

_SESSION_CACHE: dict = {}
_SESSION_TTL = 60 * 30  # 30 minutes in seconds


# ── Internal helpers ──────────────────────────────────────────────────────────

def _evict_expired() -> None:
    """Remove all sessions whose last-access timestamp is older than TTL."""
    now     = time.time()
    expired = [k for k, v in _SESSION_CACHE.items() if now - v["ts"] > _SESSION_TTL]
    for k in expired:
        del _SESSION_CACHE[k]


# ── Public API ────────────────────────────────────────────────────────────────

def cache_session(df: pl.DataFrame, col_map: dict) -> str:
    """
    Store a parsed DataFrame and its column map; return a new UUID session ID.

    Called by main.py:/process immediately after reading the uploaded file.
    Expired sessions are purged before inserting the new one.
    """
    _evict_expired()
    sid = str(uuid.uuid4())
    _SESSION_CACHE[sid] = {
        "df":           df,
        "col_map":      col_map,
        "labels":       None,   # populated later by store_labels() after clustering
        "customer_ids": None,   # populated later by store_labels() after clustering
        "ts":           time.time(),
    }
    return sid


def get_session(sid: str) -> tuple[pl.DataFrame | None, dict | None]:
    """
    Retrieve the DataFrame and column map for a session.

    Also refreshes the TTL so active users aren't evicted mid-session.
    Returns (None, None) if the session ID is unknown or has expired.
    """
    entry = _SESSION_CACHE.get(sid)
    if not entry:
        return None, None
    # Refresh last-access time to extend TTL.
    entry["ts"] = time.time()
    return entry["df"], entry["col_map"]


def store_labels(sid: str, customer_ids: list, labels: list) -> None:
    """
    Persist KMeans cluster assignments alongside the session.

    Called by clustering.py once the best-k model has been fitted.
    `customer_ids` and `labels` are parallel lists of equal length:
      customer_ids[i] → the string CustomerID
      labels[i]       → the integer cluster label (0-indexed)
    These are consumed by recommend.py to filter transactions by segment.
    """
    entry = _SESSION_CACHE.get(sid)
    if entry:
        entry["customer_ids"] = customer_ids  # list[str]
        entry["labels"]       = labels        # list[int], parallel to customer_ids
        entry["ts"]           = time.time()


def get_labels(sid: str) -> tuple[list | None, list | None]:
    """
    Return (customer_ids, labels) stored by store_labels(), or (None, None).

    Used by recommend.py to identify which customers belong to a given segment
    so that market-basket analysis can be scoped to that segment's transactions.
    """
    entry = _SESSION_CACHE.get(sid)
    if not entry:
        return None, None
    return entry.get("customer_ids"), entry.get("labels")
