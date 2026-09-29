# API — the local server's contract

Server: `http://localhost:8765` (PORT from `.env`), bound to 127.0.0.1 only, unless
`PHONE_ACCESS=on` (see "Phone access" below). Code: `server/`.
Tests: `tests/server/`.

## Store — the storage seam

The legacy app's `store` object (`legacy/drill-study-app.html`, ~line 1738) has three
methods: `get(k, tries)`, `set(k, v, verify)` and `del(k)`. (CLAUDE.md calls it
`delete`; in the code it is `del`. The app never lists keys; `list` is here for later use.)
Each maps 1:1 onto one request:

| App call | Request | Response | Adapter returns |
|---|---|---|---|
| `store.get(k)` | `GET /api/store/{k}` | **200**: body is the stored JSON text, byte for byte, `Content-Type: application/json`, header `X-Updated-At`. **204 No Content** (empty body): nothing stored under `k`. | 200 → `JSON.parse(body)`; 204 → `null` (as today) |
| `store.set(k, v, verify)` | `PUT /api/store/{k}`, body `JSON.stringify(v)` | **200** `{"ok":true,"key":k,"status":"added"\|"changed"\|"unchanged","updated_at":...}`, sent only after the write is committed. **400** `{"ok":false,"error":"bad_json",...}` if the body is not one JSON value in UTF-8 (NaN/Infinity refused). | `true` on 200, `false` otherwise or on network error. `verify` needs no read-back: the 200 comes after commit. (A read-back GET is still possible: it returns exactly the text sent.) |
| `store.del(k)` | `DELETE /api/store/{k}` | **200** `{"ok":true,"key":k,"deleted":true}`; **404** `{"ok":false,"error":"not_found",...}` if nothing was stored (nothing changes). The old value goes to `kv_history` first. | nothing (the app ignores it) |
| (list) | `GET /api/store?prefix=deck:` | **200** `{"keys":[...]}`, sorted; prefix is literal (`%` and `_` are not wildcards); no prefix = all keys | |

**Keys.** Any non-empty string, sent through `encodeURIComponent(k)`. `:`, `/`, spaces, `%`,
`?`, `#` and non-ASCII all round-trip (tested over real HTTP). Only `.` and `..` cannot be
keys: URLs treat them as "this/parent folder" even when percent-encoded. Drill never uses
them.

**Missing vs null.** A key holding JSON `null` returns 200 with body `null`. A key that does
not exist returns **204 No Content** with an empty body. The app treats both as `null`, like
today. (204, not 404: a missing key is a normal answer, for example the progress of a deck
never studied, and browsers log every 404 as a red "Failed to load resource" line.)
Deleting a missing key still answers 404.

**Caching.** Every `/api/*` response carries `Cache-Control: no-store`; app files carry
`no-cache` (the browser revalidates them).

**Values** are stored as the exact text the client sent. Writing text identical to what is
stored is a no-op: `status:"unchanged"`, no history row, `updated_at` unchanged. Any other
overwrite, and every delete, first copies the old value into `kv_history`.

Errors are JSON: `{"ok":false,"error":"<kind>","message":"..."}`.

## Other endpoints

| Request | What it does |
|---|---|
| `GET /api/health` | `{"ok":true,"app":"drill","schema":1}` |
| `POST /api/import` | Runs the importer inside the server, but **only ever adds keys**. 200 `{"ok":true,"kv_writes":n,"history_rows":n,"added_keys":[...],"undecided":[...],"skipped":[...],"snapshot":name\|null,"report":[lines]}` when it only added (or nothing was to do). **409** `{"ok":false,"error":"confirmation_required","message":...,"plan":[lines]}` when an existing key would change: nothing is written; stop the server and run `python -m server.importer`, which shows the plan and asks for `yes`. 409 `import_stopped` for any other stop (nothing written). Reload the app after an import. |
| `GET/POST /api/modules`, `POST /api/modules/{sha}/deck` | Module library (Phase 6). See "Modules" below. |
| `POST /api/ai` | The AI router (Phase 5, `server/ai.py`). See "AI" below. |
| `GET /api/ai/route` | Which model would answer a text request now, and Qwen's context: `{"model":"qwen"|"claude","num_ctx":8192}`. Used by the teacher chat to size its prompt for Qwen. |
| `GET /` and other paths | Files from `app/` (Phase 4), with `Cache-Control: no-cache`; `.woff2` fonts as `font/woff2`. If `app/index.html` does not exist when the server starts, `/` shows a placeholder page. |
| `GET /favicon.ico` | **204** (no body) unless `app/favicon.ico` exists, so the browser's automatic icon request doesn't log a 404. |

## AI — `POST /api/ai`

Body: the Anthropic Messages request the app already builds (`model` is ignored,
`max_tokens`, `messages`, optional `system`). Content blocks: `text` and base64 `image`.

**Which model.** `CLAUDE_CLI=on` and a TCP connection to api.anthropic.com:443 within 2 s
(result cached 15 s) → Claude via `claude -p`, for text **and** pictures (image blocks go in
with `--input-format stream-json`). Otherwise (offline, or `CLAUDE_CLI=off`) → Qwen. If `claude -p` fails for any reason, the request is retried once on Qwen. At most 2
`claude -p` runs at once; more wait.

**200**, the same shape whichever model ran:
`{"id","type":"message","role":"assistant","model":<model name>,"content":[{"type":"text","text":...}],"stop_reason":"end_turn"|"max_tokens","stop_sequence":null,"usage":{"input_tokens","output_tokens"},"model_used":"claude"|"qwen"}`,
plus `"fallback_from":"claude","fallback_reason":...` when Claude failed and Qwen answered.
`stop_reason` is `"max_tokens"` when Ollama says `done_reason:"length"` or `claude -p` says
`stop_reason:"max_tokens"`; anything else (or none) is `"end_turn"`. Qwen's thinking is off
(`think:false`) and any `<think>…</think>` is removed.

**Errors**, Anthropic's shape `{"type":"error","error":{"type","message"}}`:

| Status | `error.type` | When | The app |
|---|---|---|---|
| 400 | `invalid_request_error` | Prompt longer than Qwen's context: "Prompt is too long for Qwen: N tokens, limit M (OLLAMA_NUM_CTX)…". Nothing is cut or sent. Also: a PDF `document` block, a malformed body. | shows the message, no retry |
| 503 | `ai_not_configured` | No model at all: Ollama not running / model not installed, and Claude off, offline or failed. The message says which. | "AI isn't set up yet", no retry |
| 502 / 504 | `api_error` | Ollama error / Qwen timeout (`OLLAMA_TIMEOUT`, default 900 s) | retries with backoff |

**Claude** runs as `claude -p --output-format json --max-turns 1 --tools "" --no-session-persistence --strict-mcp-config --disable-slash-commands --system-prompt <short Drill prompt> [--model CLAUDE_MODEL]`
(flags checked against Claude Code 2.1.258), prompt on **stdin** as UTF-8, working folder a
new empty temp folder (deleted after), `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` removed
from its environment. The server never reads Claude Code's login.

**Qwen** gets `POST OLLAMA_URL/api/chat` with `stream:false, think:false, truncate:false,
shift:false, options:{num_ctx: OLLAMA_NUM_CTX, num_predict: max_tokens}`, images as
`images:[base64]`. `truncate:false` makes Ollama (0.34) refuse an oversize prompt with its
exact token count instead of silently cutting it; `shift:false` makes a reply that runs out
of context end with `done_reason:"length"` instead of dropping the prompt's start.

**Settings** (`.env`; a process environment variable of the same name overrides):
`OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_TIMEOUT`, `CLAUDE_CLI`,
`CLAUDE_CLI_PATH`, `CLAUDE_MODEL` (empty = Claude Code's default), `CLAUDE_TIMEOUT` (600 s),
`CLAUDE_REACH_HOST` (default `api.anthropic.com:443`; point it at an unreachable address to
simulate being offline). Read once when the server starts.

## Modules — the module library (Phase 6, `server/modules.py`)

A module PDF is identified by its **SHA-256** (the fingerprint). The flow for the app's
"build a deck from a PDF":

1. **Before building**, send the PDF: `POST /api/modules?name=<encodeURIComponent(file.name)>`,
   body = the raw file bytes (`fetch(url, {method:"POST", body: file})` with the `File`/`Blob`;
   `Content-Type: application/pdf`). Instead of `?name=`, an `X-File-Name` header
   (percent-encoded) also works. Max 400 MB; streamed to disk, never held in memory.
2. If the answer has `known: true` and `deck_exists: true`: say **"No changes: this is the
   same file as <deck_name> (uploaded <uploaded_at>)"**, open `deck_id`, and **do not build**.
   (`known:true, deck_exists:false`: the deck was deleted from the library since; build
   again and report as in step 4.)
3. If `known: false`: build as today. If `previous` is not null, this is a revised version
   of an earlier upload (same file name).
4. **After the deck is saved** (`store.set("deck:"+id, ...)` returned true), report it:
   `POST /api/modules/{sha256}/deck` with `{"deck_id": "<id>"}`. The server reads the deck
   from the database itself (terms, coverage) and answers with what changed vs the previous
   version. Show "added / changed / removed" when `first_upload` is false.

### `POST /api/modules`

| Answer | Body |
|---|---|
| **200**, same file seen before and a deck recorded | `{"ok":true,"known":true,"sha256","file_name","stored_name","deck_id","deck_name","deck_exists":bool,"pages","terms":n,"uploaded_at"}`. Nothing stored, nothing changed (a `reupload` event is logged and shows in MODULES.md). |
| **200**, new file | `{"ok":true,"known":false,"sha256","file_name","stored_name","size","resumed":false,"previous":null\|{"sha256","file_name","deck_id","deck_name","uploaded_at","terms":[names]}}` |
| **200**, same file stored before but no deck ever reported (build interrupted) | as "new file" with `"resumed":true`; nothing stored again |
| 400 `no_name` | no `?name=` / `X-File-Name` |
| 413 `too_large` | over 400 MB (Content-Length, or counted while streaming) |
| 415 `not_pdf` | body does not start with `%PDF-` |
| 403 `forbidden_origin` | Origin not this server (as for every write) |

**Storage.** `DATA_DIR\modules\<file name>` (folder parts and `<>:"|?*` removed, `.pdf`
added if missing). An existing file is **never overwritten**: if a *different* file already
has that name, the new one is stored as `<stem>-<sha8>.pdf`; if an *identical* file is
already there (same SHA-256), it is reused. Uploads land in `modules\.incoming-*.part` first
and are moved in only when complete; a failed upload leaves nothing behind.

### `POST /api/modules/{sha256}/deck`

Body `{"deck_id": "<id>"}`; optional `"pages": n` (used only when the deck has no
`coverage.pages`) and `"previous_sha": "<sha256>"` (compare against that version instead of
the automatic choice).

The server reads `deck:<id>` from `kv`: deck name (the `library` entry's name, else the
deck's), `concepts` (the terms), `coverage` (pages, content/empty/skipped slides). Pages =
`coverage.pages`, else `pages` from the body, else counted from the PDF (best effort).

**Previous version** = the newest other module with a recorded deck and the same file name
(case-insensitive); if none, the same deck name (compared with `norm`).

**Diff.** Terms are matched by `norm(name)`, the app's own
`s => (s||"").toLowerCase().replace(/[^a-z0-9]/g,"")`. A matched term is **changed** when its
content differs: `fact`, `items`, `steps` (runs of whitespace count as one space). Topic and
pages are not content: moving a term to another section is not a change.

**200** `{"ok":true,"sha256","deck_id","deck_name","pages","terms":n,"status":"recorded"|"unchanged","first_upload":bool,"previous":null|{...as above},"added":[names],"changed":[names],"removed":[names],"unchanged":n}`.
On a first upload `added` lists every term and `changed`/`removed` are empty. Reporting
the same deck again is `"unchanged"` (no write). Reporting a different deck for the same PDF
replaces the record; the replaced values are kept in `module_events`.
404 `module_not_found` (unknown sha), 404 `deck_not_found` (no `deck:<id>`), 400
`bad_request` (no `deck_id`), 403 `forbidden_origin`.

### `GET /api/modules`

`{"modules":[{"sha256","file_name","stored_name","size","pages","uploaded_at","deck_id"|null,"deck_name","deck_exists","terms","previous_sha","changes":null|{"added","changed","removed","unchanged"},"coverage":null|{...},"last_reupload_at"|null}]}`, newest upload first.

### MODULES.md

Rewritten after every module write, at the repo root **and** `DATA_DIR\MODULES.md`: a table
(file, deck, terms, pages, date, short SHA-256, change summary) and a section per upload
with the deck id, full SHA-256, coverage counts, re-uploads, and the added / changed /
removed **term names**. No facts or other study content.

### Database

`modules` (one row per distinct PDF, key `sha256`) and `module_events` (every upload,
re-upload, deck report and register, with replaced values). Nothing is ever deleted.

### Backfill CLI

`python -m server.modules register <pdf> --deck <deck id> [--name <file name>] [--previous <sha256>]`
records a PDF already on disk against a deck that already exists (Modules 2 and 3, uploaded
before Phase 6). A PDF inside `DATA_DIR\modules\` is used where it is; one elsewhere is
copied in (same no-overwrite rule). Refuses while the server runs (instance lock), if the
deck does not exist, or if the PDF is already registered to another deck. Registering the
same PDF + deck again changes nothing. `python -m server.modules list` lists what is
recorded.

## Safety guards

Checked in this order, for every request, before anything else happens:

1. **Client address.** `PHONE_ACCESS=off`: only loopback (`127.0.0.1`, `::1`). `on`: also
   Tailscale (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`), and with `PHONE_ALLOW_LAN=on` the
   private ranges (`10/8`, `172.16/12`, `192.168/16`, `fe80::/10`, `fc00::/7`). Anyone else:
   **403** `forbidden_client`. The address is the socket's peer (uvicorn runs with
   `proxy_headers=False`, so `X-Forwarded-For` cannot fake it).
2. **Host.** The `Host` header must be `localhost`, `127.0.0.1` or `[::1]`; with phone access
   on, also this PC's Tailscale IPs and MagicDNS names (full and short, detected with the
   `tailscale` CLI at start and re-checked at most every 30 s when an unknown Host arrives),
   the PC's own private IPs when `PHONE_ALLOW_LAN=on`, and the names in `PHONE_HOSTS`.
   Anything else: **403** `forbidden_host`. This blocks DNS-rebinding tricks from websites.
3. **Origin.** A `PUT`, `DELETE` or `POST` that carries an `Origin` header gets **403**
   `forbidden_origin` unless it is the server's own origin, built from the Host the request
   was addressed to: `http://<that host>:<that port>`. The local names are interchangeable
   (a page on `localhost:8765` may write to `127.0.0.1:8765`, as before); a Tailscale name
   only accepts its own origin. That includes `Origin: null` (sandboxed frames, `file://`
   pages) and an empty Origin, so no other web page open in the browser can change Drill's
   data. Requests without an Origin header (curl, scripts) are allowed; they cannot come
   from another website, because browsers always send Origin on cross-site writes.
4. **PIN** (non-loopback clients only; see "Phone access").
- One process owns `DATA_DIR` at a time (an OS lock on `DATA_DIR\drill-server.lock`, released
  automatically when the process ends). A second server, the import CLI and the restore
  CLI all refuse while the server runs.

## Phone access (Phase 8, `server/phone.py`, `server/pin.py`)

**Warning:** never put `tailscale serve` or any other proxy/forwarder on this PC in front of Drill.
The PC itself is trusted without a PIN, so forwarded phone requests would arrive as "this PC"
and skip the PIN.

The phone uses the app running on the PC over Tailscale. Settings in `.env`:

| Setting | Default | Meaning |
|---|---|---|
| `PHONE_ACCESS` | `off` | `off`: bind 127.0.0.1, this PC only (as before). `on`: bind 0.0.0.0; the guards above admit loopback + Tailscale only. |
| `PHONE_ALLOW_LAN` | `off` | `on`: also admit the home network's private addresses (still with the PIN). |
| `PHONE_HOSTS` | empty | Extra Host names to accept, comma-separated. |

With `PHONE_ACCESS=on`, `python -m server` (and so `start.bat`) prints the URL(s) to open on
the phone, whether Tailscale is installed/connected, and whether a PIN is set.

**PIN.** Loopback clients (this PC) never need one. Every other client needs a session:

| Request (non-loopback, no valid session) | Answer |
|---|---|
| no PIN set yet, any page | **403** HTML page "Set a PIN on the PC first" |
| no PIN set yet, `/api/*` or any non-GET | **401** `{"ok":false,"error":"pin_not_set",...}` |
| `GET /` | **200** the sign-in page (inline HTML/CSS, no external files, works offline) |
| `GET` any other page | **303** to `/` |
| `/api/*` or any non-GET | **401** `{"ok":false,"error":"pin_required",...}` |
| `POST /api/phone/login`, body `pin=<digits>` (form) or `{"pin":"..."}` | right PIN: **303** to `/` + cookie. Wrong: **401** sign-in page "Wrong PIN." 5th wrong in a row from one IP, or any attempt while locked: **429**, locked 15 minutes (logged to the console and to `auth_events`). A correct PIN resets the count. Lockouts are in memory: a server restart clears them. |
| `POST /api/phone/logout` | revokes this session, clears the cookie, **303** to `/` |

The cookie `drill_session` is a random 256-bit token, `HttpOnly; SameSite=Strict; Path=/;
Max-Age=2592000` (30 days, not sliding). Not `Secure`: the connection is plain HTTP inside
Tailscale's encrypted tunnel. Only its SHA-256 is stored.

**Storage.** `DATA_DIR\phone-access.db` (not the repo, not `drill.db`, so a snapshot restore
can never bring back an old PIN or revoked sessions): `pin` (salted scrypt, n=2^14 r=8 p=1;
a new PIN adds a row, the newest wins), `sessions` (token hash, created/expires, client IP,
user agent, `revoked_at`; revoking marks, never deletes), `auth_events`.

**CLI** (works while the server runs):

- `python -m server.pin set` — asks twice, 6+ digits. Setting or changing it signs every
  phone out.
- `python -m server.pin revoke-all` — sign every phone out now.
- `python -m server.pin status` — PIN set or not, signed-in phones.

**Firewall.** `tools\phone-firewall.ps1` (run once as administrator) adds one inbound
Windows Firewall rule "Drill phone access (Tailscale)": TCP `PORT` from `100.64.0.0/10` and
`fd7a:115c:a1e0::/48` only. `-Remove` removes it. It also lists any inbound block rules
for Python (Windows block rules win over allow rules) without changing them. With
`PHONE_ALLOW_LAN=on` the home network is not covered by this rule.
