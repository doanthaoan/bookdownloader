---
name: ship
description: Finish a change in this repo — verify (py_compile + npm run build), add the CHANGELOG entry with the right version bump, and propose a one-line commit message. Use after any feature/fix, or when the user says "ship", "wrap up", "done", "commit".
---

# Ship a change

1. **Verify only what changed** (`git status --short`):
   - Backend .py: `cd backend && .venv/Scripts/python.exe -m py_compile <changed files>`
   - Any `frontend/src` change: `cd frontend && npm run build`. Report only errors. Don't paste the vite output.
   - If an endpoint changed and the server is running, do one `curl http://127.0.0.1:8000/api/...` read call. Write calls follow the `db` skill backup rule.
2. **CHANGELOG.md**: read only the first ~30 lines to get the latest version. Insert a new section above it:
   - Feature → minor bump (1.4.8 → 1.5.0). Fix or tweak → patch bump (1.4.8 → 1.4.9). Several fixes in one session can share one entry.
   - Format: `## [x.y.z] — YYYY-MM-DD`, then `### Added` / `### Changed` / `### Fixed` bullets. Each bullet starts with a **bold short name**, followed by what the user notices and the key function/endpoint name.
3. **PLAN.md**: if the change completes a plan item, tick it (`- [x]`). Don't rewrite the plan.
4. **Commit message**: write one line that summarizes every change, separated by ` - ` (house style, e.g. `Fix title edit - Unblock event loop for Selenium endpoints`). Commit only if the user asked. If on master and the change is non-trivial, suggest a short-lived branch.
