"""Statistics API: aggregate request-log data with filters, daily chapter-limit
tracking with alert levels, and a limit estimator (MAX of recent days)."""

from fastapi import APIRouter, HTTPException
from datetime import date, timedelta
from typing import Optional
from app.database import get_database

router = APIRouter()
db = get_database()

# session_type values stored in request_logs.session_type
SESSION_TYPES = ("session", "non_session")


def _alert(used: int, limit: str) -> dict:
    """Build the chapter-usage alert object for one access type.

    limit '0'/'' means "no limit configured" → level 'none' (no alert).
    Otherwise: <70% ok (green), 70-89% warn (amber), >=90% danger (red).
    """
    try:
        limit = int(limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return {"level": "none", "used": used, "limit": 0,
                "remaining": None, "pct": None}
    pct = round(used * 100.0 / limit)
    if used >= limit or pct >= 90:
        level = "danger"
    elif pct >= 70:
        level = "warn"
    else:
        level = "ok"
    return {"level": level, "used": used, "limit": limit,
            "remaining": max(0, limit - used), "pct": pct}


def _limit_setting(session_type: str) -> str:
    return db.get_setting(f"chapter_limit_{session_type}") or "0"


@router.get("/meta")
async def stats_meta():
    """Distinct values present in the request log (for filter dropdowns)."""
    return db.get_request_log_meta()


@router.get("/summary")
async def stats_summary(start: Optional[str] = None, end: Optional[str] = None,
                        request_type: Optional[str] = None, status: Optional[str] = None,
                        session_type: Optional[str] = None, domain: Optional[str] = None):
    """Aggregated request stats over a date range (default: today), plus today's
    chapter-request usage vs the configured daily limits for both access types."""
    start = start or date.today().isoformat()
    end = end or start
    stats = db.get_request_stats(start, end, request_type, status, session_type, domain)

    today = date.today().isoformat()
    chapter_by_session = {}
    for row in db.get_daily_chapter_counts(today, today):
        chapter_by_session[row["session_type"]] = row["total"]

    usage = {}
    for stype in SESSION_TYPES:
        usage[stype] = _alert(chapter_by_session.get(stype, 0), _limit_setting(stype))

    return {
        **stats,
        "chapter_usage_today": usage,
        "session_mode": db.get_setting("request_session_mode") or "session",
    }


@router.get("/requests")
async def stats_requests(start: Optional[str] = None, end: Optional[str] = None,
                         request_type: Optional[str] = None, status: Optional[str] = None,
                         session_type: Optional[str] = None, domain: Optional[str] = None,
                         page: int = 1, per_page: int = 50):
    """Paginated request log entries, newest first."""
    if page < 1:
        page = 1
    per_page = max(1, min(per_page, 200))
    return db.get_request_logs(start, end, request_type, status, session_type,
                               domain, page=page, per_page=per_page)


@router.get("/daily")
async def stats_daily(start: str, end: Optional[str] = None,
                      session_type: Optional[str] = None):
    """Daily chapter-request counts (success/failed) for a date range."""
    end = end or start
    return {"days": db.get_daily_chapter_counts(start, end, session_type)}


@router.get("/limit-estimate")
async def limit_estimate(days: int = 7, session_type: str = "session"):
    """Suggest a daily chapter-request limit = MAX of the last N days' actual
    chapter requests (per user: 'Max only'). The UI can apply this as the new
    limit via the existing update-setting endpoint."""
    if days < 1:
        days = 1
    if session_type not in SESSION_TYPES:
        raise HTTPException(status_code=400, detail="session_type must be session or non_session")
    end = date.today()
    start = end - timedelta(days=days - 1)
    rows = db.get_daily_chapter_counts(start.isoformat(), end.isoformat(), session_type)
    per_day = [{"day": r["day"], "total": r["total"],
                "success": r["success"], "failed": r["failed"]} for r in rows]
    max_daily = max((r["total"] for r in per_day), default=0)
    return {
        "session_type": session_type,
        "days_requested": days,
        "days": per_day,
        "max_daily": max_daily,
        "current_limit": int(_limit_setting(session_type) or 0),
        "suggested_limit": max_daily,
    }