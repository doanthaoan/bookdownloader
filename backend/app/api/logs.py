import os
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
from app.config import TRUYENWIKI

router = APIRouter()

# Use the configured logs path, with fallback
LOGS_PATH = Path(__file__).parent.parent.parent / (TRUYENWIKI.get('logs_path', './data/logs'))


def _get_logs_dir():
    logs_dir = LOGS_PATH.resolve()
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


@router.get("/")
async def list_logs(search: str = None):
    """List all available log files."""
    logs_dir = _get_logs_dir()
    files = []
    for f in os.listdir(logs_dir):
        if f.endswith('.txt'):
            fpath = os.path.join(logs_dir, f)
            if search and search.lower() not in f.lower():
                continue
            files.append({
                "name": f,
                "size": os.path.getsize(fpath),
                "modified": os.path.getmtime(fpath),
            })
    files.sort(key=lambda x: x['name'])
    return files


@router.get("/{filename:path}")
async def read_log(filename: str, lines: int = Query(100, ge=1, le=5000), offset: int = Query(0, ge=0)):
    """Read a specific log file, with optional line limit and offset."""
    logs_dir = _get_logs_dir()
    fpath = logs_dir / filename

    # Security: prevent path traversal
    try:
        fpath = fpath.resolve()
        logs_dir_resolved = logs_dir.resolve()
        if not str(fpath).startswith(str(logs_dir_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except (ValueError, OSError):
        raise HTTPException(status_code=403, detail="Access denied")

    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
        all_lines = f.readlines()

    total = len(all_lines)
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
