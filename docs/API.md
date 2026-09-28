# API — the local server's contract

Server: `http://localhost:8765` (PORT from `.env`), bound to 127.0.0.1 only. Code: `server/`.
Tests: `tests/server/`.

## Store — the storage seam

The legacy app's `store` object (`legacy/drill-study-app.html`, ~line 1738) has three
methods: `get(k, tries)`, `set(k, v, verify)` and `del(k)`. (CLAUDE.md calls it
`delete`; in the code it is `del`. The app never lists keys; `list` is here for later use.)
Each maps 1:1 onto one request:

| App call | Request | Response | Adapter returns |
|---|---|---|---|
| `store.get(k)` | `GET /api/store/{k}` | **200**: body is the stored JSON text, byte for byte, `Content-Type: application/json`, header `X-Updated-At`. **404**: nothing stored under `k`. | 200 → `JSON.parse(body)`; 404 → `null` (as today) |
| `store.set(k, v, verify)` | `PUT /api/store/{k}`, body `JSON.stringify(v)` | **200** `{"ok":true,"key":k,"status":"added"\|"changed"\|"unchanged","updated_at":...}`, sent only after the write is committed. **400** `{"ok":false,"error":"bad_json",...}` if the body is not one JSON value in UTF-8 (NaN/Infinity refused). | `true` on 200, `false` otherwise or on network error. `verify` needs no read-back: the 200 comes after commit. (A read-back GET is still possible: it returns exactly the text sent.) |
| `store.del(k)` | `DELETE /api/store/{k}` | **200** `{"ok":true,"key":k,"deleted":true}`; **404** if nothing was stored. The old value goes to `kv_history` first. | nothing (the app ignores it) |
| (list) | `GET /api/store?prefix=deck:` | **200** `{"keys":[...]}`, sorted; prefix is literal (`%` and `_` are not wildcards); no prefix = all keys | |

**Keys.** Any non-empty string, sent through `encodeURIComponent(k)`. `:`, `/`, spaces, `%`,
`?`, `#` and non-ASCII all round-trip (tested over real HTTP). Only `.` and `..` cannot be
keys: URLs treat them as "this/parent folder" even when percent-encoded. Drill never uses
them.

**Missing vs null.** A key holding JSON `null` returns 200 with body `null`. A key that does
not exist returns 404. The app treats both as `null`, like today.

**Values** are stored as the exact text the client sent. Writing text identical to what is
stored is a no-op: `status:"unchanged"`, no history row, `updated_at` unchanged. Any other
overwrite, and every delete, first copies the old value into `kv_history`.

Errors are JSON: `{"ok":false,"error":"<kind>","message":"..."}`.

## Other endpoints

| Request | What it does |
|---|---|
| `GET /api/health` | `{"ok":true,"app":"drill","schema":1}` |
| `POST /api/import` | Runs the importer inside the server, but **only ever adds keys**. 200 `{"ok":true,"kv_writes":n,"history_rows":n,"added_keys":[...],"undecided":[...],"skipped":[...],"snapshot":name\|null,"report":[lines]}` when it only added (or nothing was to do). **409** `{"ok":false,"error":"confirmation_required","message":...,"plan":[lines]}` when an existing key would change: nothing is written; stop the server and run `python -m server.importer`, which shows the plan and asks for `yes`. 409 `import_stopped` for any other stop (nothing written). Reload the app after an import. |
| `POST /api/ai` | **Stub until Phase 5.** 503 `{"type":"error","error":{"type":"ai_not_configured","message":"..."}}` (Anthropic's error shape). |
| `GET /` and other paths | Files from `app/` (Phase 4), with `Cache-Control: no-cache`. If `app/index.html` does not exist when the server starts, `/` shows a placeholder page. |

## Safety guards

- Requests must be addressed to `localhost` or `127.0.0.1` (the `Host` header). This blocks
  DNS-rebinding tricks from websites.
- A `PUT`, `DELETE` or `POST` that carries an `Origin` header gets 403 unless that origin is
  the server's own (`http://localhost:<port>` or `http://127.0.0.1:<port>`, the port the
  request was sent to). That includes `Origin: null` (sandboxed frames, `file://` pages)
  and an empty Origin, so no other web page open in the browser can change Drill's data.
  Requests without an Origin header (curl, scripts) are allowed; they cannot come from
  another website, because browsers always send Origin on cross-site writes.
- One process owns `DATA_DIR` at a time (an OS lock on `DATA_DIR\drill-server.lock`, released
  automatically when the process ends). A second server, the import CLI and the restore
  CLI all refuse while the server runs.
