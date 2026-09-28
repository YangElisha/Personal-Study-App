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

Plus `model_used: "claude" | "qwen"` for the badge.

**Choosing the model:** Qwen is the default. If `CLAUDE_CLI=on` and a 2-second
reachability check passes, text requests go to Claude instead. Decide per request, so
losing Wi-Fi mid-session just switches over. Requests containing images always go to Qwen
(it reads images natively; `claude -p` is used for text only).

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

## Where the data lives

Everything personal lives in `DATA_DIR` — by default `C:\Users\Elish\OneDrive\DrillData` —
outside the Git folder, so it can never be committed:

```
DrillData\
  drill.db        the database
  backups\        automatic snapshots: on every start and once a day, newest 30 kept
  import\         backup files exported from Drill (read only)
  modules\        your module PDFs
```

OneDrive keeps a cloud copy of all of it. **Don't run the app on two PCs at once**, or OneDrive
can create a conflicting copy of the database. The app's own **Download a backup** still
works at any time and gives a single portable file.
