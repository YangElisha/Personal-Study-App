# API — the local server's contract

Server: `http://localhost:8765` (PORT from `.env`), bound to 127.0.0.1 only, unless
`PHONE_ACCESS=on` (see "Phone access" below). Code: `server/`.
Tests: `tests/server/`.

With `AUTH_MODE=google` (Phase 9) every request below needs a signed-in session, and the
store, modules, import and snapshots use **the signed-in account's own database**. See
"Sign-in" at the end. With `AUTH_MODE=off` (the default) everything works exactly as before.

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

**Caching.** Every `/api/*` and `/auth/*` response carries `Cache-Control: no-store`; app
files carry `no-cache` (the browser revalidates them). Security headers on every response:
see "Security headers" under "Sign-in".

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
4. **Session.** `AUTH_MODE=off`: the PIN, for non-loopback clients only (see "Phone access").
   `AUTH_MODE=google`: a valid session for **every** client, this PC included (see "Sign-in").
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

## Sign-in (Phase 9, `server/google_auth.py`, `server/accounts.py`)

`AUTH_MODE=off` (default): no sign-in; everything above works exactly as before, on
`DATA_DIR\drill.db`. `AUTH_MODE=google`: everyone signs in with an **approved** Google
account, and each account has its own database. The server refuses to start with
`AUTH_MODE=google` unless `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are in `.env` (they
are never logged or shown).

### Whose data

| Account | drill.db, backups, modules, import |
|---|---|
| the one allowed with `--existing-data` (Elisha) | `DATA_DIR` itself: the existing `drill.db`, `backups\`, `modules\`, used in place. Nothing is copied, moved or changed. The repo's `MODULES.md` stays hers. |
| every other approved account | `DATA_DIR\users\<id>\` (created with an empty `drill.db` when the account is allowed or first used; its own `MODULES.md` there, never the repo's) |

The store, `/api/modules`, `/api/import` and snapshots (on start and daily, one set per
database, each in its own `backups\`) use the signed-in account's folder. The AI endpoints
keep no per-account state (the server has no AI budget or usage record). `DATA_DIR\accounts.db`
holds the allow-list, sessions and sign-in events; it is separate from every `drill.db`, so
restoring a snapshot can never bring back a revoked session.

### Without a session (`AUTH_MODE=google`)

Every route needs a session, **this PC (loopback) included**: app files, `/api/*` (health,
store, ai, ai/route, modules, import, auth), `/favicon.ico`.

| Request | Answer |
|---|---|
| `/api/*`, or any non-GET | **401** `{"ok":false,"error":"auth_required","message":"Sign in first","sign_in":"google"}` (`"sign_in":"pin"` from a phone) |
| `GET /` | **200** the sign-in page (server-made inline HTML, no external files, works offline). If the browser sent an expired or revoked cookie it says "Your sign-in has ended" and clears the cookie. |
| `GET` any other path | **303** to `/` |
| `GET /auth/signin?error=<code>` | the sign-in page with that message (codes below; unknown codes show none) |

**Frontend contract (app/index.html):** when any `/api/*` answer is **401** with
`error:"auth_required"`, stop and load `/` (`location.href = "/"`); the server then shows the
sign-in page. Never treat a 401 as "nothing stored" (today's `store.get` already treats it as a
read failure, `readFailed = true`, and `store.set` returns false).

### The flow (OpenID Connect, authorization code + PKCE, standard library only)

1. The sign-in page's button is a plain link to `GET /auth/google/start`. It answers **302** to
   `https://accounts.google.com/o/oauth2/v2/auth` with `response_type=code`,
   `scope=openid email`, `state`, `nonce`, `code_challenge` (S256), `prompt=select_account`, and
   `redirect_uri=http://<localhost or 127.0.0.1>:PORT/auth/google/callback` (the host the page
   was opened on). It sets the cookie `drill_oauth` (random; `HttpOnly; SameSite=Lax;
   Path=/auth/google/; Max-Age=600`), which ties this sign-in to this browser. The state, nonce
   and PKCE verifier stay on the server (memory, 10 minutes, one use).
   - Opened on another host name (e.g. `[::1]` or a Tailscale name): **400** page "Open Drill
     at http://localhost:PORT/" (Google only accepts the two registered addresses).
   - Google unreachable (3-second check): **503** page with the `offline` message.
2. Google shows its account chooser, password and **2-Step Verification** (the one-time code
   is typed on Google's page; Drill never sees it), then sends the browser to
   `GET /auth/google/callback?code=...&state=...`.
3. The callback checks the state (known, unused, under 10 minutes, same browser), exchanges the
   code at `https://oauth2.googleapis.com/token` (TLS, certificate verified; sends the PKCE
   verifier and the client secret), and checks the id_token claims: `iss`
   (`https://accounts.google.com`), `aud` = our client id (and `azp` if there are several
   audiences), `exp`/`iat` with 60 s skew, `nonce`, `email_verified: true`. The signature is
   not checked separately: the token came straight from Google's token endpoint over verified
   TLS (OpenID Connect Core 3.1.3.7). Then the email must be on the allow-list
   (case-insensitive), and Google's account id (`sub`) must match the one recorded at that
   email's first sign-in.
4. Success: **200**, a tiny "Signed in" page that continues to `/` with a meta refresh, plus
   the session cookie. (A 303 does not work with `SameSite=Strict`: the redirect still belongs
   to the navigation that came from Google's site, so the browser does not send the Strict
   cookie with it. Tested in Edge 154 with a stand-in Google on another site that shows an
   account chooser: Strict + 303 lands back on the sign-in page; Strict + this page, and
   Lax + 303, both open the app. Strict is kept.)

Refusals show the sign-in page with a message code: `not_approved` (403), `account_mismatch`
(403), `retry` (400: unknown, used or expired state, or another browser's), `cancelled` (400),
`failed` (400: any token or claim problem), `offline` (503), `rate_limited` (429); also
`expired`, `signed_out`, `wrong_host`. Each refusal is logged (console and `sign_in_events`,
with the reason) and counts toward the rate limit, except `offline` and `cancelled`.

**Rate limits** (per client IP, in memory; a restart clears them): at most 20 callback
requests per 10 minutes; 10 failed sign-ins lock `/auth/google/*` for 15 minutes (429). A
successful sign-in clears the count.

### Session

Cookie `drill_session`: a random 256-bit token, `HttpOnly; SameSite=Strict; Path=/;
Max-Age=604800`. Not `Secure` (plain http on localhost). Only its SHA-256 is stored. Valid for
exactly **7 days from sign-in** (absolute: using it never extends it). It is checked locally on
every request, so it works **offline**; signing in again needs the internet. A sign-out,
disallowing the account, or `revoke-all` takes effect on the very next request.
`localhost` and `127.0.0.1` are separate sites to the browser, so each has its own session.

### Account & security API (for the account page)

All need a session and answer `Cache-Control: no-store`. POSTs must come from the app's own
page (the Origin check above). With `AUTH_MODE=off`, `/api/auth/me` answers
`{"ok":true,"auth_mode":"off","user":null,"session":null}` and the others **404**
`{"ok":false,"error":"auth_off",...}`.

| Request | Answer |
|---|---|
| `GET /api/auth/me` | `{"ok":true,"auth_mode":"google","user":{"id","email","existing_data":bool},"session":<session>}` |
| `GET /api/auth/sessions` | `{"ok":true,"sessions":[<session>...]}`: this account's active sessions, newest first |
| `GET /api/auth/events?limit=50` | `{"ok":true,"events":[{"at","event":"signed_in"\|"refused"\|"signed_out","method":"google"\|"pin"\|"cli","email","reason","client_ip","user_agent","device"}...]}`, newest first (limit 1 to 500): this account's events, including refused attempts that named its email |
| `POST /api/auth/signout` | sign out this device: `{"ok":true,"revoked":1,"signed_out_here":true}` and the cookie is cleared. Then load `/`. |
| `POST /api/auth/signout-others` | `{"ok":true,"revoked":n,"signed_out_here":false}` |
| `POST /api/auth/signout-all` | every session of this account, this one included: `{"ok":true,"revoked":n,"signed_out_here":true}`, cookie cleared |
| `POST /api/auth/sessions/{id}/revoke` | one session of this account: `{"ok":true,"revoked":1,"signed_out_here":<was it this one>}`; **404** `session_not_found` if `id` is not an active session of this account |

`<session>` = `{"id","method":"google"|"pin","device":"Edge on Windows","user_agent","client_ip","created_at","last_seen_at","expires_at","current":bool}`.
Times are ISO 8601 UTC (`2026-09-29T04:21:19Z`). `id` is not a credential. `last_seen_at` and
`client_ip` are updated at most once a minute. Every sign-out is recorded as an event.

### Phone (PIN) with sign-in on

Google cannot redirect to a plain-http Tailscale name, so with `AUTH_MODE=google` the phone
keeps the PIN, but the PIN now belongs to one account: `python -m server.pin set --email
<email>` (required in this mode; the account must be approved). A PIN session acts as that
account, lives in `accounts.db` (`method:"pin"`) and lasts **7 days** like every session.
Until a bound PIN exists the phone sees "Set a PIN for your account on the PC first" (403).
Changing the PIN or `pin revoke-all` signs out every PIN session. `/auth/*` from the phone
redirects to `/`. This PC always needs a Google session, even with phone access on.

### CLI (works while the server runs)

- `python -m server.accounts allow <email> [--existing-data]`: approve an email.
  `--existing-data`: this account uses `DATA_DIR` itself; one account only; an existing
  account's data folder is never changed.
- `python -m server.accounts disallow <email>`: refuse it and sign it out now (its data is kept).
- `python -m server.accounts list`, `sessions [--email E]`, `revoke-all [--email E]`,
  `events [--email E] [--limit N]`.
- `--user <email>` on `python -m server.importer`, `python -m server.restore`,
  `python -m server.modules register|list` and `tools\verify_import.py`: work on that account's
  folder. Without it they use `DATA_DIR` itself, exactly as before.

### Security headers (every response, both modes)

`Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src
'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:;
font-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'
https://accounts.google.com`, plus `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`. Checked in headless Edge 154 with the
real app: library, vendored fonts, pdf.js in its Web Worker (`readFile` + `renderPdfPage` on a
PDF with embedded fonts), backup download: 0 CSP violations. For future app changes: no
`fetch()` of `data:`/`blob:` URLs, no external hosts, no `eval`.

### Google Cloud Console

Authorized redirect URIs (both): `http://localhost:8765/auth/google/callback` and
`http://127.0.0.1:8765/auth/google/callback` (your `PORT` if it is not 8765). The client ID
and secret go in `.env` only.
