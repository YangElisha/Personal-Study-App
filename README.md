# Personal Study App (Drill)

A study app that turns lecture modules into decks, lessons, tests and games — running on
this PC, offline, with Claude when online and Qwen when not.

**Start here:** `docs/SETUP-GUIDE.md` (step by step), then `docs/PLAN.md`.
Claude Code reads `CLAUDE.md` automatically.

AI: Qwen3.5 9B offline by default; Claude through the official Claude Code program when
online. No API key.

| Folder | |
|---|---|
| `legacy/` | The app as it left Claude.ai — the reference, never edited |
| `app/` | The local version (created in Phase 4) |
| `server/` | The local server and database (Phase 3); start with `start.bat` |
| `docs/` | Plan, architecture, migration, offline AI |
| `.claude/agents/` | Claude Code subagents, one per job |
| `tests/` | Reader regression tests on real modules |

**Start:** double-click `start.bat`. The first start needs internet once (it installs the
Python packages into `.venv`); after that everything runs offline.

Your data (database, backups, module PDFs) lives in `OneDrive\DrillData`, outside this
folder, and is never uploaded to GitHub.
