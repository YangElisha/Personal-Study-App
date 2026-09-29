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
| `phone.py` | Phone access (Phase 8): which clients and Host names are admitted, Tailscale detection, PIN hash, sessions, lockout, sign-in page. Contract in `docs/API.md`. |
| `pin.py` | `python -m server.pin set [--email] / revoke-all / status` |
| `google_auth.py` | Sign in with Google (Phase 9): OIDC code flow + PKCE, claim checks, rate limits, the sign-in page. Contract in `docs/API.md` "Sign-in". |
| `accounts.py` | Approved accounts, sessions, sign-in events (`DATA_DIR\accounts.db`), which folder each account's data is in; `python -m server.accounts` |
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

## Phone access (Phase 8)

```
Phone (Tailscale app) --WireGuard tunnel--> PC 100.x.y.z:PORT --> same server, same drill.db
```

The phone does not get its own copy of anything: it opens the app served by the PC, so
there is nothing to sync, and Qwen/Claude run on the PC as usual. `PHONE_ACCESS=off`
(default) keeps the server on 127.0.0.1. `on` binds 0.0.0.0, and three layers keep
everyone else out: the Windows Firewall rule (`tools\phone-firewall.ps1`, Tailscale
addresses only), the server's client-address check (loopback + Tailscale, 403 otherwise),
and a PIN for every device other than the PC (session cookie, 30 days, revocable from the
PC). Host and Origin checks still apply, with this PC's Tailscale names added. The PC
itself stays PIN-free. Nothing is exposed to the internet: Tailscale addresses are only
reachable from devices signed in to Elisha's tailnet. Details: `docs/API.md`
"Phone access".

## Sign-in and one database per person (Phase 9)

```
Browser --"Sign in with Google"--> accounts.google.com (password, 2-Step Verification)
   <-- code -- /auth/google/callback --(TLS)--> oauth2.googleapis.com/token --> id_token
Server: claims OK + email approved --> session (7 days, checked locally, works offline)
every request --> session --> that account's folder --> its own drill.db / modules / backups
```

`AUTH_MODE=off` (default) is today's behaviour exactly. `AUTH_MODE=google` puts a session in
front of everything, this PC included. The allow-list, sessions and sign-in events live in
`DATA_DIR\accounts.db`, apart from every `drill.db` (a snapshot restore cannot bring back a
revoked session). Elisha's account is mapped to `DATA_DIR` itself, so her existing
`drill.db`, `backups\` and `modules\` are used where they are; anyone else gets
`DATA_DIR\users\<id>\`. The store, modules, import and snapshots take the signed-in account's
folder from the request; the CLI tools take `--user <email>` and default to `DATA_DIR` as
before. The one instance lock still covers all of `DATA_DIR`. Only the Google client ID and
secret are needed, in `.env`; no extra Python packages (urllib, hashlib, secrets). The phone
keeps the PIN (Google cannot redirect to a plain-http tailnet name), now bound to one account.
Every response carries a Content-Security-Policy and the usual hardening headers. Details:
`docs/API.md` "Sign-in".

## Where the data lives

Everything personal lives in `DATA_DIR` — by default `C:\Users\Elish\OneDrive\DrillData` —
outside the Git folder, so it can never be committed:

```
DrillData\
  drill.db        the database
  backups\        automatic snapshots: on every start and once a day, newest 30 kept
  import-decisions.json   Elisha's import decisions, read by the importer (Phase 3)
  drill-server.lock       empty file the running server locks (one process at a time)
  phone-access.db         phone PIN hash + phone sessions (Phase 8; only if a PIN was set)
  accounts.db     approved accounts, sessions, sign-in events (Phase 9; AUTH_MODE=google)
  import\         backup files exported from Drill (read only)
  modules\        your module PDFs
  users\<id>\     another approved account's own drill.db, backups\, modules\, import\ (Phase 9)
```

OneDrive keeps a cloud copy of all of it. **Don't run the app on two PCs at once**, or OneDrive
can create a conflicting copy of the database. The app's own **Download a backup** still
works at any time and gives a single portable file.
