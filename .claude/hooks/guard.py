"""PreToolUse (Bash|PowerShell): block shell commands that touch private/bulky data.

Read/Grep/Glob are covered by deny rules in settings.json; this covers `cat`, `ls`, `Get-Content`...
"""
import json
import re
import sys

BLOCKED = re.compile(
    r"data[\\/]+downloads|translate_src|\.docx\b|(^|[\s\"'=/\\])raw[\\/]",
    re.IGNORECASE,
)

cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
if BLOCKED.search(cmd) and not cmd.lstrip().startswith("git "):
    print("Blocked by project guard: downloads/, raw/, translate_src/ and *.docx are off-limits "
          "unless the user explicitly names the file. Ask the user first.", file=sys.stderr)
    sys.exit(2)
