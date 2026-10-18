"""Statistics API: aggregate request-log data with filters, daily chapter-limit
tracking with alert levels, and a limit estimator (MAX of recent days).

Mounted in main.py under the prefix ``/api/stats``, so ``@router.get("/meta")``
here is really ``GET /api/stats/meta``.

All endpoints are plain ``def`` on purpose: FastAPI runs them in a thread pool,
so the blocking sqlite queries do not stall the asyncio event loop that serves
every other request.

Data comes from the ``request_logs`` table (one row per HTTP request the
downloader made to the book site). Every endpoint here is read-only.
"""

from fastapi import APIRouter, HTTPException
from datetime import date, timedelta
from typing import Optional
from app.database import get_database

router = APIRouter()
# One shared Database helper for this module (get_database() returns a singleton).
db = get_database()

# session_type values stored in request_logs.session_type
# ("session" = requests made while logged in with cookies, "non_session" = anonymous).
# A tuple (immutable) is used because this is a fixed constant.
SESSION_TYPES = ("session", "non_session")


def _alert(used: int, limit: str) -> dict:
    """Build the chapter-usage alert object for one access type.

    limit '0'/'' means "no limit configured" → level 'none' (no alert).
    Otherwise: <70% ok (green), 70-89% warn (amber), >=90% danger (red).

    Why: the site rate-limits how many chapters you can read per day. The UI
    shows a coloured badge so you stop downloading before hitting the wall.

    Args:
        used:  chapters requested today for this access type.
        limit: the configured daily limit, as stored in settings (a string).

    Returns:
        ``{"level": "none"|"ok"|"warn"|"danger", "used": int, "limit": int,
        "remaining": int|None, "pct": int|None}``

    Example: used=75, limit="100" -> pct=75 -> level "warn", remaining 25.
    """
    # Settings are stored as text, so convert defensively; garbage -> "no limit".
    # (Reusing the `limit` name for the int version is legal but changes its type.)
    try:
        limit = int(limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return {"level": "none", "used": used, "limit": 0,
                "remaining": None, "pct": None}
    pct = round(used * 100.0 / limit)
    # `used >= limit` catches the edge where rounding would hide a full quota.
    if used >= limit or pct >= 90:
        level = "danger"
    elif pct >= 70:
        level = "warn"
    else:
        level = "ok"
    # max(0, ...) so going over the limit shows 0 remaining, never negative.
    return {"level": level, "used": used, "limit": limit,
            "remaining": max(0, limit - used), "pct": pct}


def _limit_setting(session_type: str) -> str:
    """Return the configured daily chapter limit for an access type, as a string.

    Reads the setting ``chapter_limit_session`` or ``chapter_limit_non_session``;
    ``or "0"`` turns a missing/empty setting into "0" (= no limit).
    """
    return db.get_setting(f"chapter_limit_{session_type}") or "0"


@router.get("/meta")
def stats_meta():
    """GET /api/stats/meta -- distinct values present in the request log
    (for the filter dropdowns: request types, statuses, session types, domains).

    Response: whatever ``db.get_request_log_meta()`` returns (a dict of lists).
    """
    return db.get_request_log_meta()


@router.get("/summary")
def stats_summary(start: Optional[str] = None, end: Optional[str] = None,
                        request_type: Optional[str] = None, status: Optional[str] = None,
                        session_type: Optional[str] = None, domain: Optional[str] = None):
    """Aggregated request stats over a date range (default: today), plus today's
    chapter-request usage vs the configured daily limits for both access types.

    GET /api/stats/summary

    Query params (all optional; ``Optional[str] = None`` means "may be omitted"):
        start, end:   ISO dates "YYYY-MM-DD". start defaults to today, end to start.
        request_type, status, session_type, domain: exact-match filters.

    Response: the stats dict from ``db.get_request_stats`` merged with
        ``"chapter_usage_today": {"session": <alert>, "non_session": <alert>}``
        (see ``_alert``) and ``"session_mode"`` (current request mode setting).

    Note: chapter_usage_today always covers TODAY, regardless of start/end,
    because the daily limit resets per day.
    """
    start = start or date.today().isoformat()
    end = end or start
    stats = db.get_request_stats(start, end, request_type, status, session_type, domain)

    # Build {session_type: chapters_today} from today's per-type counts.
    today = date.today().isoformat()
    chapter_by_session = {}
    for row in db.get_daily_chapter_counts(today, today):
        chapter_by_session[row["session_type"]] = row["total"]

    # One alert object per access type; .get(stype, 0) covers "no requests yet".
    usage = {}
    for stype in SESSION_TYPES:
        usage[stype] = _alert(chapter_by_session.get(stype, 0), _limit_setting(stype))

    # `**stats` unpacks the stats dict into this new dict, then the extra keys
    # are added alongside it (a shallow merge).
    return {
        **stats,
        "chapter_usage_today": usage,
        "session_mode": db.get_setting("request_session_mode") or "session",
    }


@router.get("/requests")
def stats_requests(start: Optional[str] = None, end: Optional[str] = None,
                         request_type: Optional[str] = None, status: Optional[str] = None,
                         session_type: Optional[str] = None, domain: Optional[str] = None,
                         page: int = 1, per_page: int = 50):
    """GET /api/stats/requests -- paginated request log entries, newest first.

    Query params: same filters as /summary (all optional, no date defaults here),
    plus ``page`` (1-based, default 1) and ``per_page`` (default 50, clamped 1..200).

    Response: the paginated dict from ``db.get_request_logs`` (entries + totals).
    """
    # Manual clamping keeps bad input from erroring. The FastAPI-native way is
    # declaring the bounds: page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200)
    # (that returns 422 instead of silently clamping).
    if page < 1:
        page = 1
    per_page = max(1, min(per_page, 200))
    return db.get_request_logs(start, end, request_type, status, session_type,
                               domain, page=page, per_page=per_page)


@router.get("/daily")
def stats_daily(start: str, end: Optional[str] = None,
                      session_type: Optional[str] = None):
    """GET /api/stats/daily -- daily chapter-request counts (success/failed) for a date range.

    Query params:
        start:        REQUIRED ISO date (no default -> FastAPI returns 422 if missing).
        end:          optional ISO date, defaults to start (a single day).
        session_type: optional filter ("session" / "non_session").

    Response: ``{"days": [{"day", "total", "success", "failed", ...}, ...]}``
    """
    end = end or start
    return {"days": db.get_daily_chapter_counts(start, end, session_type)}


@router.get("/limit-estimate")
def limit_estimate(days: int = 7, session_type: str = "session"):
    """Suggest a daily chapter-request limit = MAX of the last N days' actual
    chapter requests (per user: 'Max only'). The UI can apply this as the new
    limit via the existing update-setting endpoint.

    GET /api/stats/limit-estimate

    Query params:
        days:         how many days back to look, including today (default 7, min 1).
        session_type: "session" (default) or "non_session".

    Response:
        ``{"session_type", "days_requested", "days": [per-day counts],
        "max_daily", "current_limit", "suggested_limit"}``

    Errors: 400 if session_type is not one of SESSION_TYPES.

    Why MAX: the busiest day you got through without being blocked is the best
    evidence of what the site actually allows.
    """
    if days < 1:
        days = 1
    if session_type not in SESSION_TYPES:
        raise HTTPException(status_code=400, detail="session_type must be session or non_session")
    end = date.today()
    # days - 1 because the range is inclusive: days=7 -> today plus the 6 days before.
    start = end - timedelta(days=days - 1)
    rows = db.get_daily_chapter_counts(start.isoformat(), end.isoformat(), session_type)
    # List comprehension: copy only the fields the UI needs from each row.
    per_day = [{"day": r["day"], "total": r["total"],
                "success": r["success"], "failed": r["failed"]} for r in rows]
    # default=0 makes max() return 0 for an empty list instead of raising ValueError.
    max_daily = max((r["total"] for r in per_day), default=0)
    return {
        "session_type": session_type,
        "days_requested": days,
        "days": per_day,
        "max_daily": max_daily,
        "current_limit": int(_limit_setting(session_type) or 0),
        # TODO: identical to max_daily for now; kept separate so the formula can
        # change later (e.g. add a safety margin) without breaking the UI contract.
        "suggested_limit": max_daily,
    }
