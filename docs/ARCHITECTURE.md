# ARCHITECTURE

## The idea in one line

Keep the app as it is. Put a small local server behind it that does the two jobs the
Claude.ai sandbox used to do for it: **remember things** and **talk to an AI**.

```
 Browser (app/index.html — the legacy app, two seams swapped)
    │  fetch /api/store/...                fetch /api/ai
    ▼                                       ▼
 Local server (localhost:8765)
    ├── Store  ── SQLite  DATA_DIR\drill.db   (+ snapshots in DATA_DIR\backups)
    ├── Modules ─ DATA_DIR\modules\*.pdf  + fingerprints + coverage  → MODULES.md
    └── AI router
          ├── online + CLAUDE_CLI=on → `claude -p` (official Claude Code, your subscription)
          └── otherwise              → Ollama → Qwen3.5 9B (local, offline)
```

## The two seams

The legacy app already routes everything through two functions. Only these change.

### 1. Storage — `store.get / store.set / store.delete / store.list`

| Today (Claude.ai) | Local |
|---|---|
| `window.storage` key-value, per card | `GET/PUT/DELETE /api/store/{key}`, `GET /api/store?prefix=` |

Keys stay exactly as they are (`library`, `deck:<id>`, `prog:<id>`, `prefs`,
`exam:<id>`). The database is one table:

```sql
CREATE TABLE kv (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,          -- the same JSON the app stores today
  updated_at TEXT NOT NULL
);
CREATE TABLE kv_history (             -- every overwrite is kept: nothing is ever lost
  key TEXT, value TEXT, replaced_at TEXT
);
```

Keeping the app's own key-value shape means no data has to be *translated* — which is
where migrations usually lose things. `kv_history` means a bad write can always be undone.

As built (Phase 3, `server/db.py`): `kv` and `kv_history` exactly as above, plus an index on
`kv_history(key)`. Every overwrite **and every delete** copies the old value into
`kv_history` first; writing text identical to what is stored is a no-op (no history row,
`updated_at` kept). WAL mode, one transaction per write. Three small bookkeeping tables
belong to the importer, not to the app: `import_files` (SHA-256 of each backup file
imported), `import_notes` (Elisha's notes such as "rename later") and
`import_decisions_applied` (which one-off import decisions have run). The request/response
contract is in `docs/API.md`.

### 2. AI — `claudeRawCall(content, maxTokens)`

| Today | Local |
|---|---|
| POST to Anthropic from the browser | POST `/api/ai` with the same body |

The server answers in **Anthropic's response shape** whichever model ran, so the app's
cut-off detection (`stop_reason: "max_tokens"`) keeps working:

| Anthropic | Ollama | Returned to the app |
|---|---|---|
| `content[0].text` | `message.content` | `content: [{type:"text", text}]` |
| `stop_reason: "max_tokens"` | `done_reason: "length"` | `stop_reason: "max_tokens"` |
| image block (base64) | `images: [base64]` | — |
| PDF document block | not supported | app already renders pages to images first |

Plus `model_used: "claude" | "qwen"` for the badge (bottom-left of the app: "AI: Claude",
"AI: Qwen", or "AI: Qwen (Claude failed)" — when Claude fails the request is retried once on
Qwen and the reply carries `fallback_from:"claude"` and the reason).

**Choosing the model:** Qwen is the default. If `CLAUDE_CLI=on` and a 2-second
reachability check passes, every request goes to Claude instead — text and pictures
(Elisha, 2026-09-29: Claude whenever online, Qwen only offline). Pictures reach `claude -p`
as image blocks via `--input-format stream-json`. Decide per request, so losing Wi-Fi
mid-session just switches over. If Claude fails online (e.g. usage limit), the request is
retried once on Qwen and the badge says so.

### Calling Claude without an API key

The server runs the official `claude` program in headless mode for each request:

- the prompt is written to its **standard input**, never the command line — Windows limits a
  command line to ~32,000 characters and Drill's prompts can be longer
- it runs from an **empty temporary folder**, so Claude Code doesn't load this repo's
  CLAUDE.md into every study question
- tools are disabled and it gets one turn: it should answer, not act
- output in JSON, translated into the shape the app expects
- confirm the exact flags with `claude --help` — they change between versions

This draws from Elisha's Claude subscription, the same limits as using Claude Code
interactively (per Anthropic's Help Center as of September 2026 — this rule has changed
several times, so if it stops working, set `CLAUDE_CLI=off` and everything runs on Qwen).
Never extract Claude Code's login token for direct use — that is what gets accounts suspended.

## Offline requirements

The legacy app loads three things from the internet. All must be vendored:

| Loaded from | Used for | Local copy |
|---|---|---|
| cdnjs — pdf.js 3.11.174 + worker | reading PDFs | `app/vendor/pdfjs/` |
| Google Fonts | typefaces | `app/vendor/fonts/` (or system fallback) |
| api.anthropic.com | AI | replaced by `/api/ai` → Qwen / `claude -p` |

## Server choice

Python + FastAPI + the built-in `sqlite3` module — the same stack family as ScholarSync,
one process, no external database to install. Node + Express is an acceptable alternative;
decide in Phase 3 and record the choice in CHANGELOG.md.

**Decided in Phase 3: Python 3.12 + FastAPI + uvicorn + built-in `sqlite3`**, in a
repo-local `.venv` (gitignored), pinned in `requirements.txt` (tests: `requirements-dev.txt`).
Code in `server/`:

| File | Job |
|---|---|
| `settings.py` | Reads `.env` (a process environment variable of the same name overrides it). Refuses to start if `DATA_DIR` is inside the repo, missing, or relative. |
| `app.py` | The FastAPI app: store API, `/api/import`, `/api/ai`, static `app/`. |
| `ai.py` | The AI router (Phase 5): routing, `claude -p`, Ollama, Anthropic response shape. Contract in `docs/API.md`. |
| `db.py` | Schema and the one write path (history before every overwrite/delete). |
| `modules.py` | Module library (Phase 6): `/api/modules` logic, MODULES.md, `python -m server.modules register`. Contract in `docs/API.md`. |
| `snapshots.py` | Snapshots with SQLite's backup API, pruning. |
| `importer.py` | `python -m server.importer` — see DATA-MIGRATION.md. |
| `restore.py` | `python -m server.restore <snapshot>` |
| `instance_lock.py` | One process owns `DATA_DIR` at a time. |
| `__main__.py` | `python -m server [--open]`; `start.bat` runs it with `--open`. |

**Snapshots.** On every start, and every 24 hours while running (checked every 10
minutes), the database is copied with SQLite's backup API to
`DATA_DIR\backups\drill-YYYYMMDD-HHMMSS.db` (local time; `-2`, `-3`… if two land in the
same second). Each snapshot is a standalone file (no `-wal`), integrity-checked, and
written under a temporary name first, so a snapshot file is always complete. Only files
matching exactly that name pattern are pruned, newest `BACKUP_KEEP` kept. Safety snapshots
taken before an import (`...-pre-import.db`) or a restore (`...-pre-restore.db`) do not
match the pattern and are never pruned.

**Restore.** `python -m server.restore` lists snapshots; `python -m server.restore <name>`
refuses while the server runs, shows what would be replaced (key and deck differences),
asks you to type `yes`, snapshots the current database as `...-pre-restore.db`, then copies
the snapshot in with the backup API. Restoring the pre-restore file undoes a restore.

## Where the data lives

Everything personal lives in `DATA_DIR` — by default `C:\Users\Elish\OneDrive\DrillData` —
outside the Git folder, so it can never be committed:

```
DrillData\
  drill.db        the database
  backups\        automatic snapshots: on every start and once a day, newest 30 kept
  import-decisions.json   Elisha's import decisions, read by the importer (Phase 3)
  drill-server.lock       empty file the running server locks (one process at a time)
  import\         backup files exported from Drill (read only)
  modules\        your module PDFs
```

OneDrive keeps a cloud copy of all of it. **Don't run the app on two PCs at once**, or OneDrive
can create a conflicting copy of the database. The app's own **Download a backup** still
works at any time and gives a single portable file.
