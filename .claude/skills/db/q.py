"""Read-only query against the live DB. Long cells are truncated so chapter content never floods context.

usage: backend/.venv/Scripts/python.exe .claude/skills/db/q.py "SELECT ..." [max_cell_chars=120]
"""
import sqlite3
import sys
from pathlib import Path

db = Path(__file__).resolve().parents[3] / "backend" / "data" / "novel_downloader.db"
sql = sys.argv[1]
width = int(sys.argv[2]) if len(sys.argv) > 2 else 120

sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252; titles are Vietnamese
conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)  # writes raise
cur = conn.execute(sql)
cols = [d[0] for d in cur.description or []]
rows = cur.fetchmany(200)
print(" | ".join(cols))
for r in rows:
    print(" | ".join((s if len(s := str(v)) <= width else s[:width] + f"…(+{len(s) - width})").replace("\n", "⏎") for v in r))
if len(rows) == 200:
    print("… truncated at 200 rows; add LIMIT/WHERE")
