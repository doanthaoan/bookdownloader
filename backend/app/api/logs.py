"""Logs API: list and read the plain-text log files written by the downloader.

Mounted in main.py under the prefix ``/api/logs``, so ``@router.get("/")`` here is
really ``GET /api/logs/``.

Why plain ``def`` and not ``async def``?  FastAPI runs plain ``def`` endpoints in
a thread pool, so slow blocking work (file I/O here; Selenium / sqlite in other
routers) does not freeze the single asyncio event loop that serves every request.
An ``async def`` endpoint doing blocking work would stall the whole server.
"""
import os
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
from app.config import logs_dir

# An APIRouter is a "mini app": endpoints are registered on it with decorators,
# and main.py plugs it into the real FastAPI app with app.include_router(...).
router = APIRouter()


@router.get("/")
def list_logs(search: str = None):
    """GET /api/logs/ -- list the available ``.txt`` log files.

    Query params:
        search: optional case-insensitive substring filter on the file name.

    Response: a JSON list, sorted by name:
        ``[{"name": str, "size": bytes, "modified": unix_timestamp_float}, ...]``

    Read-only; no side effects (except logs_dir() creating the folder if missing).
    """
    # Named `folder` (not `logs_dir`) so it doesn't shadow the imported logs_dir() function.
    folder = logs_dir()
    files = []
    for f in os.listdir(folder):
        if f.endswith('.txt'):
            fpath = os.path.join(folder, f)
            if search and search.lower() not in f.lower():
                continue
            files.append({
                "name": f,
                "size": os.path.getsize(fpath),
                "modified": os.path.getmtime(fpath),
            })
    # sort(key=...) sorts in place; the lambda picks the dict field to compare on.
    files.sort(key=lambda x: x['name'])
    return files


# `{filename:path}` uses Starlette's "path" converter: unlike a normal `{param}`,
# it also matches "/" so sub-folders like "2024/run.txt" work. That flexibility is
# exactly why the path-traversal guard below is required.
@router.get("/{filename:path}")
def read_log(filename: str, lines: int = Query(100, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """GET /api/logs/{filename} -- read a slice of one log file.

    Path param:
        filename: file name relative to the logs folder (may contain "/").
    Query params:
        lines:  how many lines to return, default 100. ``Query(100, ge=1, le=5000)``
                means "default 100, must be >= 1 and <= 5000"; FastAPI rejects
                anything else with HTTP 422 before this function even runs.
        offset: 0-based line index to start from (>= 0).

    Response:
        ``{"filename", "total_lines", "offset", "returned_lines", "content"}``
        where ``content`` is the selected lines joined into one string.

    Errors: 403 if the path escapes the logs folder, 404 if the file is missing.
    Read-only.
    """
    folder = logs_dir()
    # Path objects overload "/" to join path segments.
    fpath = folder / filename

    # Security: prevent path traversal.
    # A request like GET /api/logs/../../app/config.py would otherwise read any
    # file on disk. resolve() turns the path absolute and collapses ".." parts;
    # then we check the result still lives inside the logs folder.
    try:
        fpath = fpath.resolve()
        # is_relative_to() checks real path containment. A plain string
        # startswith() would also accept a sibling folder such as
        # ".../logs_old/x.txt", because it starts with ".../logs".
        if not fpath.is_relative_to(folder.resolve()):
            raise HTTPException(status_code=403, detail="Access denied")
    except (ValueError, OSError):
        # resolve() can fail on malformed/invalid paths -- treat as denied too.
        raise HTTPException(status_code=403, detail="Access denied")

    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    # errors='replace' swaps undecodable bytes for "?" instead of raising, so a
    # log with a stray non-UTF-8 byte still displays.
    # TODO: readlines() loads the whole file into memory just to return a slice;
    # itertools.islice over the file object would scale to huge logs.
    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()

    total = len(all_lines)
    # Clamp start/end so an offset past the end returns an empty slice, not an error.
    start = min(offset, total)
    end = min(start + lines, total)
    content = ''.join(all_lines[start:end])

    return {
        "filename": filename,
        "total_lines": total,
        "offset": start,
        "returned_lines": end - start,
        "content": content,
    }
