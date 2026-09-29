# CHANGELOG

Newest first. Every change gets an entry in the same commit.

## [Unreleased]

### Changed — reorganised app, branding, loading screen (Elisha, 2026-09-29)
- **Layout:** sidebar = logo, Home (Today), Library, Review (due count), New deck; Subjects
  (folders collapsed except the current one, one line per deck with a due badge, Archive last);
  Backups, Appearance, Settings at the bottom. Today: one next action, recently studied decks,
  progress at a glance. Library: subjects as sections of deck cards, search + subject filter;
  folder rename/colour/delete live here. Review: everything due, by deck. Deck page: Study,
  Teach me, "Test & games" and "What to study" menus, a "…" menu for rare actions; tabs
  Overview · Guide · Terms · Cards · Manage. Settings: AI status, global study options (moved
  from each deck's "Session options"), appearance, version.
- **Backups view:** download / restore a backup file, the server's snapshot list, "Take a
  snapshot now". Server: `GET /api/backups`, `POST /api/backups/snapshot` (manual snapshots are
  never pruned; nothing can be deleted or restored from the app — restoring stays
  `python -m server.restore`). `/api/health` reports the version.
- **Branding:** icon, logo and README cover from Elisha's orb artwork
  (`assets/monospace-logo-source.png`, `packaging/make_icon.py`); exe, installer, window and
  favicon use it.
- **Loading screen** (`app/splash.css`, `app/splash.js`): rotating wireframe sphere, glowing core,
  orbiting moons, MONOSPACE title, "Loading your decks…"; at least 1.2 s, hides when boot finishes
  (or after 8 s), then stops and removes itself; still frame with reduced motion.
- **Data:** no stored key or JSON shape changed; old backups restore as before. Checked on a copy
  of the real database in headless Edge: 74/74 browse checks with kv/kv_history unchanged, 7/7
  write checks (only the expected keys changed), a backup download → restore round trip identical,
  contrast ≥ 4.5:1 in all presets at 1280/1440/1920, 0 JS errors, 0 non-local requests; reader
  tests 3/3; 215 server tests. A safety snapshot was taken first
  (`drill-20260929-153138-pre-restructure.db`).
- Found, not fixed: `startSprint()` (the 60-second sprint) has no button; true before this change.

### Added — MonoSpace 1.0.0 for Windows (2026-09-29)
- `MonoSpace.exe` (server/launcher.py, PyInstaller): runs the server in-process on 127.0.0.1
  and opens the app in its own window (Edge app mode, private profile). Closing the last window
  stops the server cleanly; a second launch opens another window, never a second server; a busy
  port → the next free one. First run: a small dialog chooses the data folder (default
  %USERPROFILE%\MonoSpaceData) and writes %APPDATA%\MonoSpace\settings.env. Logs in
  %LOCALAPPDATA%\MonoSpace\logs. `MONOSPACE_HOME=<folder>` redirects all of it for tests.
- Downloads built by `packaging\build.ps1`: `MonoSpace-Setup.exe` (Inno Setup, per-user, no
  admin, Start menu + desktop icon; the uninstaller never removes data or settings) and
  `MonoSpace-1.0.0-portable.zip`. Unsigned (SmartScreen: "More info → Run anyway").
- App icon (assets/monospace.ico), also served as /favicon.ico. 205 server tests.
- Elisha's data moved to a new folder name: `OneDrive\MonoSpaceData` is a verified copy of
  `DrillData` (every file byte-identical, every table row-identical, import verifier PASS);
  `.env` points at it. `DrillData` is left untouched as a backup.

### Removed (Elisha, 2026-09-29: MonoSpace is local-only, free and open source, no sign-in)
- Phase 9 (Google sign-in, accounts, one database per person) and Phase 8 (phone access over
  Tailscale with a PIN). Deleted server/google_auth.py, accounts.py, phone.py, pin.py,
  tools/phone-firewall.ps1 and their tests; no PHONE_*, AUTH_MODE, GOOGLE_* settings or --user
  flags. The server binds 127.0.0.1, answers loopback only, checks Host and Origin, one DATA_DIR.
  Kept: security headers on every response (CSP form-action now 'self'), tools/check_secrets.py.
  Any accounts.db / phone-access.db / users\ left in a DATA_DIR are untouched and not read.

### Changed
- App: **MonoSpace** rename and premium redesign (app/index.html + Inter font vendored, OFL).
  Phase 9 app code removed. Title, wordmark, dialogs and toasts say MonoSpace; new backups
  download as `monospace-backup-<date>.json`; old Drill backups are still accepted; store keys
  unchanged. New presets: "MonoSpace" (dark, default), "MonoSpace Light", "Neutral" (old ones
  kept, plus user-saved presets). Near-black gradient, glass bars, card sheen, 180 ms
  transitions, visible focus rings. One-time switch on first start: your colours are kept as
  "Classic (my colours)", MonoSpace is turned on, prefs get `msTheme:1` (written once; never when
  prefs failed to load). Checked in headless Edge: text and muted text ≥ 4.5:1 in all three new
  presets, 0 JS errors, 0 non-local requests, reader tests 3/3.
- Renamed to **MonoSpace** (server side): start.bat, console messages, placeholder page,
  MODULES.md header, the claude -p system prompt, log names, package.json. Unchanged for
  compatibility: store keys, drill.db and its tables, drill-<ts>.db snapshots, DATA_DIR.
- README rewritten as an install guide; MIT LICENSE added.

### Added
- `tools/export_public.py`: makes the clean public copy (no history; leaves out CLAUDE.md, .claude/,
  PLAN/DATA-MIGRATION/SETUP-GUIDE, legacy/, the real course fixtures, CHANGELOG/MODULES), then
  scans it for personal markers, course material and secrets. The reader test skips fixtures
  that aren't present. Comments and test names made generic (no personal names or paths).
- Phase 9 (app, marked "LOCAL PORT (Phase 9)"): with AUTH_MODE=google, an account chip (initials,
  email on hover, no image) opens "Account & security": signed in as / since / ends, active
  sessions with per-session Sign out and "Sign out all other devices", the last 20 sign-in events,
  Sign out, and a note on Google 2-Step Verification. Any 401 `auth_required` shows "You've been
  signed out — sign in again" and loads the sign-in page; a 401 is a read failure, never empty
  data, and nothing is written. With AUTH_MODE=off nothing changes. Checked offline in headless
  Edge with a stand-in Google: 24/24 + 3/3 checks, 0 CSP violations, 0 other hosts.
- Phase 9 (server): Google sign-in, one database per person. `AUTH_MODE=off|google` (default off
  = unchanged). google: every request, this PC included, needs a session; the server refuses to
  start without `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (in `.env` only). OpenID Connect code
  flow + PKCE, state bound to the browser, nonce, id_token claims checked, approved emails only,
  Google account id pinned per email; standard library only. Sessions in `DATA_DIR\accounts.db`
  (hashed), HttpOnly SameSite=Strict cookie, exactly 7 days, checked locally (works offline),
  revocable instantly; sign-in events logged; rate limits per IP. The `--existing-data` account
  (Elisha) uses DATA_DIR's existing drill.db/modules/backups in place; others get
  `DATA_DIR\users\<id>\`. `python -m server.accounts allow|disallow|list|sessions|revoke-all|events`;
  `/api/auth/*` for the account page; `--user` on importer/restore/modules/verify_import; phone PIN
  bound to an account. Security headers on every response (CSP, nosniff, no-referrer, DENY),
  checked in headless Edge with the real app and pdf.js (0 violations). `tools/check_secrets.py`
  scans the repo and git history: no secrets found. 277 tests.
- Phase 8 (server): phone access over Tailscale. `PHONE_ACCESS=off|on` (default off = this PC
  only, as before). On: only this PC and Tailscale addresses are answered (`PHONE_ALLOW_LAN=on`
  adds home Wi-Fi); everyone else gets 403 first. The PC's Tailscale names are detected
  automatically (+ `PHONE_HOSTS`). Every other device needs a PIN: `python -m server.pin
  set|revoke-all|status`; scrypt hash and hashed 30-day sessions in `DATA_DIR\phone-access.db`;
  5 wrong PINs → 15-minute lockout; changing the PIN signs every phone out. Offline sign-in page
  served by the server. `tools\phone-firewall.ps1` adds a Tailscale-only firewall rule.
- Phase 6, app side (marked "LOCAL PORT" in app/index.html; PLAN Phase 6 asks for it): a build
  from exactly one PDF first sends it to `/api/modules`. The same PDF as an existing deck →
  "No changes: this is the same PDF as your deck “…”" and that deck opens; nothing is built.
  Otherwise it builds as before, records the deck, and logs "First upload of this module" or
  "Changes since the last upload: added …; changed …; removed …". If the library can't be
  reached, it builds anyway. Multi-file or pasted-text builds are not checked or recorded.
- Phase 6 (server side): module library, `server/modules.py`. `POST /api/modules` takes the
  raw PDF (streamed to disk, up to 400 MB), fingerprints it with SHA-256 and answers
  `known:true` + the deck for a file seen before (the app says "no changes" and skips the
  build), or stores it in `DATA_DIR\modules\` (never overwriting: a different file with the
  same name gets `-<sha8>`, an identical one is reused). `POST /api/modules/{sha}/deck
  {deck_id}` records the built deck, reading its terms and coverage from `kv` itself (the
  app sends only the id), and returns added / changed / removed term names vs the previous
  version (same file name, else same deck name; names matched with the app's `norm`,
  content = fact + items + steps). `GET /api/modules` lists them. New tables `modules`,
  `module_events` (every write logged, replaced values kept, nothing deleted). MODULES.md
  regenerated after every write, in the repo and in `DATA_DIR`. Backfill CLI:
  `python -m server.modules register <pdf> --deck <id>`. Contract in `docs/API.md`.
- Tests: `tests/server/test_modules.py` (18: known = no changes, stored and never
  overwritten, name-clash suffix, identical file reused, added/changed/removed diff,
  MODULES.md, Origin refusal, register CLI, 150 MB upload over real HTTP with peak Python
  memory under 64 MB). Test servers write MODULES.md to the scratch folder, never the repo.
- AI routing (Elisha, 2026-09-29): **Claude whenever online, Qwen only offline** — pictures
  now go to Claude too when online (image blocks through the official `claude -p
  --input-format stream-json`; real check: Module 2 slide 24's risk matrix transcribed
  exactly in 5.8 s, `model_used:"claude"`). If Claude fails online (e.g. usage limit), the
  request still falls back once to Qwen (her choice), and the badge says so.
- Phase 5 close (2026-09-29): `OLLAMA_NUM_CTX=8192` (100% GPU on the 8 GB card; 16384 ran 12%
  on the CPU). `GET /api/ai/route` says which model would answer a text request and Qwen's
  context. Teacher chat: when Qwen will answer, the module text is sized to fit 8192 tokens
  (and the oldest messages dropped if needed); Claude keeps 22,000 characters and 8 messages.
  Real check on the largest deck: before, 7,825-token prompt, reply cut off; after, 4,615
  tokens, reply complete, `ollama ps` 100% GPU.
- Phase 5: the AI router, `server/ai.py`, behind `POST /api/ai` (the 503 stub is gone; 503
  `ai_not_configured` now means "no model available at all"). Images → Qwen; text →
  `claude -p` when `CLAUDE_CLI=on` and api.anthropic.com:443 answers within 2 s; otherwise
  Qwen; a failed Claude call is retried once on Qwen (`fallback_from:"claude"`). Always
  Anthropic's shape plus `model_used`; `done_reason:"length"` / Claude `max_tokens` →
  `stop_reason:"max_tokens"`. `claude -p` (flags checked on 2.1.258): prompt on stdin, empty
  temp folder, `--tools ""`, `--max-turns 1`, JSON, no session saved, API-key variables
  removed from its environment, at most 2 at once. Ollama: `num_ctx` from `.env`,
  `think:false`, `truncate:false` + `shift:false` so an oversize prompt is refused with its
  exact token count (400 `invalid_request_error`), never cut. Contract in `docs/API.md`.
  New optional settings: `OLLAMA_TIMEOUT`, `CLAUDE_MODEL`, `CLAUDE_TIMEOUT`,
  `CLAUDE_REACH_HOST`; the AI settings can be overridden by process environment variables.
- `app/index.html`: model badge (bottom-left, "AI: Claude" / "AI: Qwen" / "AI: Qwen (Claude
  failed)"): one call in `claudeRawCall`'s success path plus a `modelBadge` function (16
  added lines, nothing else changed). Reader tests 3/3.
- Tests: `tests/server/test_ai.py` (21, fake Ollama + fake `claude` program
  `tests/server/fake_claude.py`); every server test now points the router at a closed port
  with `CLAUDE_CLI=off` (conftest), so no test reaches the real models.
- Real checks 2026-09-28 (scratch DATA_DIR): Qwen and `claude -p` answer through the server;
  40,000-character prompt reached `claude -p` whole; Qwen near-limit prompt whole, over-limit
  refused; Module 2 slide 24 transcribed by Qwen; `ollama ps` **not** 100% GPU at 16384
  (12%/88%), 100% at 8192 — see OFFLINE-AI.md.
- Phase 4: `app/index.html` = the legacy app with only the two seams swapped plus vendored
  assets (diff vs legacy: 32 insertions, 46 deletions). `store.get/set/del` → `/api/store`
  (server is the only store, "Saved on this PC"); `claudeRawCall` → `/api/ai`, same body, no
  API key, no `navigator.onLine` check, `ai_not_configured` fails at once. pdf.js 3.11.174 in
  `app/vendor/pdfjs/` (sha512 = cdnjs SRI), fonts in `app/vendor/fonts/` (OFL). No `http(s)://`
  left in `app/index.html`. Checked in headless Edge with every host but localhost blocked, on
  a scratch copy of the database: all requests local, 0 failed; 18/18 decks match; a study
  session saved and survived a browser restart; pdf.js ran in a real worker; reader tests 3/3.
- `tools/verify_import.py` (stdlib only, read-only: `drill.db` opened `mode=ro`, files `rb`):
  independent of `server/importer.py`. Per deck, expected (backup files, merged by id) vs found
  (drill.db) for concepts, questions, flashcards, study-guide entries, problem courses/problems,
  progress records and folder, cross-checked against INVENTORY.md and its SHA-256s; deep and
  byte-level comparison of every `deck:`/`prog:`/`library`/`prefs`/`exam:` value, with Elisha's
  decisions recomputed as the only allowed differences; extra keys, `kv_history`, import notes
  and applied decisions checked. Exit 1 on any mismatch. `--after-study` for Phase 7 (more is
  allowed, nothing from the backups may be missing).
- Phase 3: local server and database (`server/`, `start.bat`, `requirements*.txt`,
  `pytest.ini`, `tests/server/`, `docs/API.md`).
  - **Stack decision: Python 3.12 + FastAPI 0.141 + uvicorn 0.54 + built-in `sqlite3`**
    (the default in ARCHITECTURE.md). Repo-local `.venv` (gitignored); runtime pins in
    `requirements.txt`, test pins (pytest, httpx2 for Starlette's TestClient) in
    `requirements-dev.txt`. Settings are read only from `.env`; a process environment
    variable overrides a `.env` value (used by the tests for a scratch DATA_DIR).
  - Server on 127.0.0.1:PORT only; serves `app/` (placeholder page until Phase 4). Store API
    `GET/PUT/DELETE /api/store/{key}`, `GET /api/store?prefix=`; contract in `docs/API.md`,
    mapped 1:1 to the legacy `store.get/set/del`. Values stored as the exact JSON text
    sent; missing key = 404, stored `null` = 200 `null`. Every overwrite and delete copies
    the old value to `kv_history`; an identical write is a no-op. WAL, one transaction per
    write. `/api/ai` is a 503 stub (`ai_not_configured`) until Phase 5. Refuses to start if
    `DATA_DIR` is inside the repo, missing or relative. Host/Origin checks so other
    websites cannot write. One process owns DATA_DIR at a time (OS lock on
    `DATA_DIR\drill-server.lock`).
  - Snapshots with SQLite's backup API on every start and every 24 h while running:
    `DATA_DIR\backups\drill-YYYYMMDD-HHMMSS.db`, newest `BACKUP_KEEP` kept; only that exact
    pattern is pruned. Pre-import / pre-restore safety snapshots are never pruned.
  - Restore CLI `python -m server.restore <snapshot>`: refuses while the server runs, shows
    what changes, requires typing `yes`, snapshots the current DB first.
  - Importer `python -m server.importer` / `POST /api/import`: reads every
    `DATA_DIR\import\drill-backup-*.json` read-only (SHA-256 checked before and after),
    snapshots first (only when it will write), merges oldest-exported first (Drill's `mergeDeck` and `norm` ported
    exactly; per-concept further-along progress; library order, colours, names and folders
    kept), then applies Elisha's decisions from `DATA_DIR\import-decisions.json` in a
    second transaction, each once. Idempotent. Details: DATA-MIGRATION.md → "How the
    import works".
  - `start.bat` (double-click): creates `.venv` and installs requirements on first run
    (and when `requirements.txt` changes), starts the server, opens the browser once it
    answers.
  - Tests (pytest) on synthetic data in temp folders, incl. a real-HTTP uvicorn test for
    URL decoding (Starlette's TestClient decodes paths twice, so `%` keys are tested there).
  - Review fixes (Phase 3 review, NOT READY → fixed):
    - **Rule 2: the importer asks before changing existing data.** It now plans everything
      in memory first (merge + not-yet-applied decisions) and lists keys to add, each
      existing key that would change with what changes (concepts added/replaced,
      flashcards, progress records replaced and by which tie-break, deck-level fields,
      nCon/nQ, folders, library entries), and unchanged keys. Adding needs no
      confirmation. Changing an existing key needs a typed `yes` in the CLI (`--yes` for
      scripts); `POST /api/import` never changes one and answers 409
      `confirmation_required` with the plan. A no-op run writes nothing and takes no
      snapshot. A failing check or decision now writes nothing at all (previously the merge
      was already committed). A guard stops any plan that would drop a folder, deck,
      concept, flashcard or progress record.
    - **Origin check:** `Origin: null` is no longer exempt; a PUT/DELETE/POST carrying any
      Origin other than the server's own (`http://localhost:<port>` /
      `http://127.0.0.1:<port>`) gets 403.
    - Progress records without `box` are compared the way the app's `migrate()` reads
      them (stored verbatim). merge_prog stops, writing nothing, if either side's progress,
      `m` or a record is not an object, so the file's `m` can never be dropped.
    - The merge keeps an existing deck's `name` (like the library entry), so a fuller file
      copy cannot undo a rename inside `deck.name`.
    - DATA-MIGRATION.md: the deck-level progress rule is described accurately (Drill gives
      a tie to the backup; the import gives it to the database).
    - Tests use invented names only.
    - `start.bat`: if requirements changed but cannot be installed (offline), it warns and
      starts with the existing `.venv`. CLAUDE.md/README: the first run needs internet
      once.
- Phase 2: slide-reader regression test. `npm test` reads the reader out of
  `legacy/drill-study-app.html` at runtime (never copied into the test), runs it on
  `tests/fixtures/` in the app's own order — `slidesFromUpload`, then the activity-slide
  step `setAsideActivities`, then the self-check `auditSlides` (the opening of the app's
  `resolveSlides`; the test checks the app still opens that way and stops with exit code 2
  if not) — and compares the terms left after activity slides are set aside with
  `tests/golden/`: term names, topics, items, steps and pages, plus content/image/skipped
  slides; the self-check must flag zero slides. The number of slides/terms set aside is
  printed. `--html <path>` points it at another copy (Phase 4:
  `npm test -- --html app/index.html`). Node only, no npm dependencies, no network.
  Files: `package.json`, `tests/run-reader-tests.js`, `tests/lib/extract-reader.js`.
  Result 2026-09-28: Module 2 → 30 terms, Module 3 → 23 terms, all identical, 0 set
  aside on both; a one-line break in `toLines` and a one-line break in
  `setAsideActivities` (set aside every content slide) each fail both modules (exit code 1).
  Neither real module has an activity slide, so on its own this missed a break that stops
  `setAsideActivities` setting activities aside. **Closed by a synthetic fixture:**
  - New fixture + golden file (Elisha's approval, 2026-09-28):
    `tests/fixtures/synthetic-activity-text.json` and
    `tests/golden/synthetic-activity.expected.json`. **Why:** without an activity slide
    in any fixture, nothing checked that activities are set aside. The fixture is
    hand-built, in the same `{page: {items, imgs}}` shape, with invented text only (no
    course content, no personal data; marked SYNTHETIC in `tests/fixtures/README.md` and in
    the golden file's `note`). Its six pages are a cover, a divider and three one-term
    content slides (Widget, Gadget, Sprocket), plus slide 5 "ACTIVITY 1" ("Submit your
    answers before Friday."). The golden file was generated from the legacy reader
    only after checking by hand that its output is the intended reading: 3 terms kept,
    slide 5 and its term "Activity 1" set aside, 0 self-check flags.
  - The test now also asserts which slides are set aside, exactly (page, title, reason,
    terms, in order), against a new golden field, `setAside`. A golden file without it
    expects none, so Modules 2 and 3 are held to 0 set aside. Their fixtures and golden
    files are unchanged. `npm test` runs all three fixtures.
  - Proof: with `if(!why) return;` → `return;` in `setAsideActivities` (activities kept),
    the synthetic fixture FAILS (extra term "Activity 1", slide 5 not set aside), exit
    code 1. Before this change the same break passed with exit code 0. The earlier breaks
    still fail: `toLines` 1, set-aside-everything 1, resolveSlides reordered 2.
- Starter kit: CLAUDE.md, docs/ (PLAN, ARCHITECTURE, DATA-MIGRATION, OFFLINE-AI),
  six subagents in .claude/agents/, legacy app frozen in legacy/, reader regression
  fixtures and golden files for IA Modules 2 and 3.

### Fixed
- Reader (app/index.html `slidesFromUpload`): a full-slide background image no longer counts
  as a picture. Why: re-capturing Module 3 from the real PDF showed every page has exactly one
  image, a Canva background (118% of the page area), so the title-only dividers p6 "Purpose of
  Security Control" and p12 "Types of Security Controls" were classed as picture slides and
  sent to the AI, and terms 2–10 got the wrong topic. The picture count now follows the
  drawing transform in the operator list and skips images covering >= 90% of the page
  (`pg.view`). Module 2's real pictures cover 12–28%, so slide 24 is still a picture slide.
  This was the "Found, not fixed" item on the Module 3 fixture (Elisha's advance decision,
  2026-09-28). Golden files unchanged.
- Fixtures `module2-text.json` and `module3-text.json` re-captured from the module PDFs
  (Elisha's approval) with pdf.js 3.11.174: text items byte-identical to before; each page is
  now `{items, imgs, view, images}` (imgs = image paint operations, view = page box,
  images = the transform at each image paint). The test replays those transforms so the
  background rule is exercised. Module 3 is no longer a bare items array.

### Changed
- Reader test: default target is now `app/index.html` (`--html <file>` for any other).
  `legacy/drill-study-app.html` stays the frozen reference; it still counts Canva
  backgrounds as pictures and so fails the Module 3 fixture (imageSlides [6,12], topics) —
  expected, and proof the test catches that bug.
- Server (Phase 4 follow-up, clean browser console): `GET /api/store/{key}` for a missing key
  answers **204 No Content** instead of 404 (a stored JSON `null` is still 200 `null`;
  DELETE of a missing key is still 404); `GET /favicon.ico` answers 204 unless
  `app/favicon.ico` exists; `.woff2` is served as `font/woff2`; every `/api/*` response has
  `Cache-Control: no-store`. docs/API.md and the server tests updated.
- No API key: Qwen3.5 9B via Ollama by default, Claude via the official `claude -p` when online.
- Personal data moved out of the repo to `DATA_DIR` (OneDrive\DrillData) with automatic snapshots.
- Legacy app updated: backup v2 includes settings and unfinished Test papers; restore
  merges deck content and can never shrink a deck.
- Added docs/SETUP-GUIDE.md (step by step).
- Added .gitattributes (`* -text`): Git no longer converts line endings, so the frozen
  legacy app and test fixtures stay byte-for-byte identical on every checkout.
- docs/DATA-MIGRATION.md: defined "further-along" for one concept's progress record —
  higher box wins; if tied, more right answers; if still tied, most recently seen.
- docs/DATA-MIGRATION.md: third "further-along" tie-break is now the later next-review
  date (`due`) — Drill keeps no per-concept "last seen" date (`seen` is a count). The
  wrong claim that this is "the same rule Drill's own restore uses" is replaced by an
  accurate description: restore merges content the same way but keeps one side's
  progress for the whole deck, chosen by `asked`.
- docs/PLAN.md and docs/DATA-MIGRATION.md: any `drill-backup-*.json` file name is accepted.
- docs/PLAN.md: Phase 0 boxes ticked (verified 2026-09-28).
- docs/DATA-MIGRATION.md: "further-along" completed (Elisha, 2026-09-28) — a concept
  with a record in only one copy keeps that record; if next-review dates also tie, the
  record from the fuller deck copy is kept.

### Migration
- Phase 3 import into `DATA_DIR\drill.db` (2026-09-28): 1 file
  (`drill-backup-2026-09-28.json`, sha256 `e75f6c96…0ba9`, unchanged after import).
  29 keys written as in the file (18 `deck:`, 9 `prog:`, `prefs`, `library`), then
  Elisha's decisions: `muaicdxx9pud` renamed "IA Module 3 (old build)" and moved to a new
  "Archive" folder (`f-archive`, last); CLO3/TLO7–9 confirmed absent from `mui02dwojkee`;
  progress carry-over compared all 6 shared concepts and `mui02dwojkee`'s record won each
  (every `muaicdxx9pud` record is box 0, right 0), so `prog:mui02dwojkee` is unchanged;
  "rebuild from PDF after Phase 4" (2 decks) and "rename later" (5 decks) recorded in
  `import_notes`. Totals read back: 18 decks, 506 concepts, 1,859 questions, 506
  flashcards, 19 guide entries, 4 problem courses, 217 progress records (= INVENTORY.md).
  Second run: 0 kv writes, 0 history rows.
- Phase 1 done: `DATA_DIR\import\INVENTORY.md` built from the backup `drill-backup-2026-09-28.json`
  (18 decks, 506 concepts, 1,859 questions, 506 flashcards, 217 progress records). Nothing
  was imported. Elisha's import decisions are recorded in INVENTORY.md:
  - "IA Module 3": `mui02dwojkee` is the real deck; `muaicdxx9pud` is archived as
    "IA Module 3 (old build)" and progress on matching concept names carries over.
  - NLP Modules 2 and 3 are to be rebuilt from their PDFs after Phase 4.
  - The same-named Module 1/2 decks stay separate and are marked "rename later".

- app/index.html: restore dialog, backup note and comment now say what restore really does:
  deck content is only added to, and progress is taken per deck from whichever side has
  answered more questions (Elisha, 2026-09-28; outside the two seams by her decision).

### Fixed (visual polish, Elisha 2026-09-29; app/index.html, marked "LOCAL PORT (polish)")
- Measured in headless Edge, both themes, 1440x900 and 1280x720 (before → after):
  - dark primary buttons: text contrast 3.1 → 6.2:1;
  - light muted text: 2.7–3.1 → 4.6–5.2:1; light sidebar muted: 4.0 → 6.3:1;
  - the study bar no longer covers the question card (15 px overlap → 0) or the sidebar, and its
    stats are centred on the content;
  - "Ask the teacher" no longer hides page ends (more bottom space);
  - big buttons line up with their neighbours (a legacy `.big` class clash);
  - home-page text 8.5–10.9 px → 11–12.5 px; sidebar folder names no longer cut off;
  - New deck labels aligned; text boxes and the flashcard hint use the normal font.

### Fixed (usability pass, Elisha 2026-09-29; app/index.html, marked "LOCAL PORT")
- Server unreachable at startup: the app says "Can't reach the Drill server" and writes nothing,
  instead of opening an empty library and saving it (or default settings) over the real ones;
  a restore no longer treats an unanswered settings read as "no settings".
- A failed save now shows "Not saved — the Drill server isn't answering…" (was silent).
- The unused "Anthropic API key" card is hidden (no key is ever used).
- Online/offline text says where AI answers come from (Claude online, Qwen on this PC offline);
  messages no longer talk about "this browser's storage" or "your connection".
- After a revised module is built, the "changes since the last upload" summary also shows as a
  toast (the build log is off-screen once the deck opens).
- Checked in headless Edge on a scratch copy: normal start, a 503 on `library` at start (dialog,
  0 writes), and a save with the server down (toast).
- Phone layout (Phase 8 mobile part) stopped at Elisha's request; the phone-access server
  remains, off by default.

### Found, not fixed
- The same-PDF check ignores the page range.
- Deleting a key that was never stored (e.g. `prog:` of a never-studied deck) logs a 404 line
  in the browser console; harmless.
