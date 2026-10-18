"""PostToolUse (Edit|Write): syntax-check edited backend .py files. Silent on success."""
import json
import sys

path = (json.load(sys.stdin).get("tool_input") or {}).get("file_path") or ""
if path.endswith(".py") and "backend" in path.replace("\\", "/"):
    try:
        with open(path, encoding="utf-8") as f:
            compile(f.read(), path, "exec")  # builtin compile: no .pyc written
    except SyntaxError as e:
        print(f"SyntaxError in {path}:{e.lineno}: {e.msg}", file=sys.stderr)
        sys.exit(2)
