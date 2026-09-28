# CHANGELOG

Newest first. Every change gets an entry in the same commit.

## [Unreleased]

### Added
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

### Changed
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

### Found, not fixed
- Legacy boot writes an empty library/default prefs if reading them fails but the next save
  succeeds (recoverable from `kv_history`). Failed saves are silent.
- The unused "Anthropic API key" card is still shown in Manage; offline/AI help texts still talk
  about "this browser" and "your connection".
- Deleting a key that was never stored (e.g. `prog:` of a never-studied deck) logs a 404 line
  in the browser console; harmless.
- The two fixtures are saved in different shapes: `module2-text.json` is
  `{page: {items, imgs}}`, `module3-text.json` is `{page: [items]}` with no picture
  count. The test accepts both and takes a missing count as 0, so for Module 3 it cannot
  tell a title-over-a-picture slide from a divider. Fixtures left unchanged (Elisha,
  2026-09-28). **When Module 3's fixture is re-captured from the PDF:** check whether its
  title-only divider slides start being classed as picture slides because of Canva
  full-slide background images. If they do, the reader needs a fix to tell full-slide
  backgrounds from real pictures.
