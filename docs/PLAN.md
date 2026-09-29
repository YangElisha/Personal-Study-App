# PLAN — moving Drill onto this PC

Work top to bottom. A phase is finished only when every "done when" line has been run
and passed. Tick the boxes as you go and commit after each phase.

---

## Phase 0 — Repo and VS Code (today)

**Owner:** you + Claude Code

- [x] Git is installed: `git --version` prints a version
- [x] This kit is unzipped into the `Study App` folder
- [x] The folder is linked to `github.com/YangElisha/Personal-Study-App` and pushed
- [x] `.gitignore` is in place **before** the first commit

**Done when:** the repo on GitHub shows `CLAUDE.md`, `docs/`, `.claude/agents/`,
`legacy/`, `tests/` — and **no** PDFs, `.env` or database files.

**Phase 0 done 2026-09-28** — checked: git 2.54, `.gitignore` in the first commit, `main`
pushed to GitHub, no PDFs / `.env` / database files tracked.

Full click-by-click instructions: `docs/SETUP-GUIDE.md`.

---

## Phase 1 — Get every bit of data out of Drill (lossless export)

**Owner:** `migration-guardian` · **Where:** in Claude.ai, then this repo

1. ✅ Done in Claude.ai: the newest Drill card's backup (v2) includes settings and
   unfinished Test papers, and restoring can no longer shrink a deck.
2. Open **every** Drill card you have used — each card has its own storage, and your
   decks are spread across several of them.
3. In each: **Manage → Download a backup → Copy**. Paste into Notepad, save as
   `DATA_DIR\import\drill-backup-<anything>.json` — any `drill-backup-*.json` name is
   accepted (e.g. `drill-backup-01.json`, `drill-backup-2026-09-28.json`). One file per card.
4. Put the original module PDFs into `DATA_DIR\modules\` (Drill never stored them).

**Done when:**
- [x] One backup file per card, each valid JSON — *2026-09-28: one v2 file from the newest
      card (valid UTF-8 JSON). Older cards not checked: Elisha decided they are checked and
      exported before they are retired in Phase 7.*
- [x] `migration-guardian` has produced `DATA_DIR\import\INVENTORY.md`: per file, the deck
      names, concept counts, question counts and progress-record counts — *18 decks, 506
      concepts, 1,859 questions, 217 progress records; recount PASS*
- [x] You have looked at INVENTORY.md and confirmed every deck you care about is listed —
      *2026-09-28; her import decisions are recorded in INVENTORY.md → "Decisions"*

**Phase 1 done 2026-09-28.** Step 4 (module PDFs into `DATA_DIR\modules\`) is still open;
they are needed by Phase 4.

Nothing is deleted from Claude.ai. The old cards stay as a second copy until Phase 7 passes.

---

## Phase 2 — Freeze the reference and build the safety net

**Owner:** `reader-qa`

1. `legacy/drill-study-app.html` is committed untouched.
2. Write a test runner that pulls the slide reader out of the legacy HTML, feeds it
   `tests/fixtures/module2-text.json` and `module3-text.json`, and compares the result
   with `tests/golden/`.

**Done when:**
- [x] `npm test` (or the chosen command) passes: Module 2 → 30 terms, Module 3 → 23 terms,
      names, topics, steps and items identical to the golden files — *2026-09-28: both
      modules PASS, pages identical too, self-check flags 0 on both; exit code 0. The terms
      compared are those left after the app's activity-slide step (`slidesFromUpload` →
      `setAsideActivities` → `auditSlides`, as `resolveSlides` runs them); 0 slides set
      aside on both modules.*
- [x] Deliberately breaking one line of the reader makes the test fail (proves the net works)
      — *2026-09-28: in scratch copies of the HTML, (a) `toLines` changed to drop text
      fragments of 3 characters or fewer, and (b) `setAsideActivities` changed to set aside
      every content slide; each makes both modules FAIL, exit code 1. Legacy file untouched.
      Neither real module has an activity slide, so a break that stops activity slides
      being set aside used to pass. Closed 2026-09-28 (Elisha's approval) by a third,
      synthetic fixture (`tests/fixtures/synthetic-activity-text.json`, invented text; see
      `tests/fixtures/README.md`). It has one activity slide, and its golden file pins both
      the kept terms and the set-aside slide (`setAside`). Modules 2 and 3 are held to 0
      set aside. With (c) `if(!why) return;` → `return;` in `setAsideActivities`, the
      synthetic fixture FAILS, exit code 1. (a) and (b) still exit 1, and a reordered
      `resolveSlides` exits 2.*

---

## Phase 3 — Local server and database

**Owner:** `backend-builder`

- A small local server (see ARCHITECTURE.md) that
  - stores what Drill stores, in SQLite at `DATA_DIR\drill.db`
  - snapshots the database to `DATA_DIR\backups\` on start and daily, keeping 30
  - serves the app at `http://localhost:8765`, started by double-clicking `start.bat`
  - imports the backup files from `DATA_DIR\import\`

**Done when:**
- [x] Import of every backup file succeeds — *2026-09-28: `drill-backup-2026-09-28.json`
      into `DATA_DIR\drill.db`, exit 0; file SHA-256 unchanged; Elisha's decisions applied*
- [x] A verification script prints, per deck, *expected vs found* for concepts, questions,
      flashcards and progress records — and every row matches — *`tools/verify_import.py`
      (independent of the importer): 18/18 decks, 506 concepts, 1,859 questions, 506
      flashcards, 217 progress records; content byte-identical except the documented
      decisions; exit 0*
- [x] Importing the same file twice changes nothing (merge, never duplicate) — *second run:
      0 kv writes, 0 history rows; kv/kv_history byte-identical on a scratch copy*
- [x] Where two cards had the same deck, no concept from either copy is missing — *only one
      card exported so far, so proven on two synthetic backups sharing a deck id (verifier
      exit 0; removing a concept from either copy makes it exit 1). Re-run in Phase 7.*
- [x] Restarting the server creates a snapshot in `DATA_DIR\backups\`, and restoring one works
      — *two starts on the real DATA_DIR made two snapshots; restore tested on a scratch copy
      only (change reverted, pre-restore snapshot kept)*

**Phase 3 done 2026-09-28.**

---

## Phase 4 — Run the app locally

**Owner:** `frontend-porter`

- Copy `legacy/drill-study-app.html` to `app/index.html`
- Replace **only** the storage layer and the AI call
- Vendor pdf.js and the fonts so nothing loads from the internet

**Done when:**
- [ ] With Wi-Fi **off**: the app opens, every imported deck is there, a study session
      saves progress, and reopening the browser keeps it — *2026-09-28: passed in headless
      Edge with every host except localhost blocked (scratch copy of the DB): all requests
      local, 0 failed; 18/18 decks; progress saved and kept after a browser restart.
      **Open:** Elisha to repeat once by hand with real Wi-Fi off.*
- [x] Building a deck from `modules/MODULE3_S-ITCS318.pdf` with Wi-Fi off gives the same
      23 terms (this path needs no AI) — *2026-09-28, headless Edge, every host but localhost
      blocked, scratch DB: 23/23 terms, names/topics/pages/items identical to the golden file,
      0 self-check flags, 0 AI requests. First run failed (Canva backgrounds made dividers
      p6/p12 "picture" slides); fixed in e71bf34.*
- [x] Phase 2 tests still pass against `app/index.html` — *3/3 fixtures, exit 0*

---

## Phase 5 — Qwen by default, Claude when online (no API key)

**Owner:** `ai-router`

- One endpoint the app calls. Qwen through Ollama by default; when online and
  `CLAUDE_CLI=on`, text requests go to the official `claude -p`. It always answers in the
  shape the app already expects.
- A small badge in the app shows which model answered.

**Done when:**
- [ ] Online: teacher chat and essay marking answer via Claude (`claude -p`) — 2026-09-28: a text request through `/api/ai` answered by real `claude -p` (`model_used:"claude"`); not yet run from the app's own teacher chat / essay marking
- [ ] Wi-Fi off: the same features answer via Qwen, with no change in the app — 2026-09-28: only simulated (reachability check pointed at an unreachable address → Qwen); needs a real Wi-Fi-off run in the app
- [x] `CLAUDE_CLI=off`: everything answers via Qwen — 2026-09-28, real server, `/api/ai` → `model_used:"qwen"`
- [x] A prompt longer than 32,000 characters reaches `claude -p` whole (sent on stdin) — 2026-09-28, 40,000 chars, real `claude -p` echoed the start and end markers
- [x] A prompt near the context limit reaches Qwen **whole**, or is refused loudly — 2026-09-28, 16,104 tokens whole (markers echoed); 16,512 and 18,671 refused with a 400 naming the count
- [x] A picture slide (Module 2, slide 24) is read by Qwen — 2026-09-28, rendered as the app does (pdf.js, 1400 px JPEG), sent to the `CLAUDE_CLI=on` server: Qwen transcribed the whole risk matrix
      *2026-09-29: routing changed (Elisha) — online, pictures now go to Claude (slide 24
      transcribed exactly via `claude -p`); Qwen reads them offline, as checked above.*
- [x] `ollama ps` shows 100% GPU during a long request — 2026-09-29: **5.5 GB, 100% GPU at
      num_ctx 8192** during a worst-case teacher-chat request (4,615-token prompt + reply).
      16384 had failed (12%/88% CPU/GPU on 2026-09-28, still after an orphaned runner was
      stopped).

**Why `OLLAMA_NUM_CTX=8192` (Elisha, 2026-09-29):** it is the largest context that keeps the
whole Qwen model on the 8 GB RTX 5060 (100% GPU); 12288 and 16384 put ~12% on the CPU. Longer
prompts go to Claude when online, or are refused loudly offline — never cut.

**Teacher chat at 8192:** module text (up to 22,000 characters) + the last 8 messages + a
900-token reply did not fit. Measured with the real model on NLP Module 4 (the largest deck):
the old prompt took 7,825 of 8,192 tokens and the reply was cut off (`max_tokens`). Now, only
when Qwen will answer (`GET /api/ai/route`), the chat shrinks the module text and, if needed,
drops the oldest messages: the same case became 4,615 tokens and the reply ended normally.
Claude still gets 22,000 characters and 8 messages.

---

## Phase 6 — Module library and change log

**Owner:** `backend-builder`

- Every uploaded module is saved in `DATA_DIR\modules\`, fingerprinted, and recorded in the database
  with its coverage report
- `MODULES.md` is regenerated: each module, its deck, term count, date, and what changed
  since the last upload
- App changes are recorded in `CHANGELOG.md`

**Done when:**
- [x] Uploading Module 2 again reports "no changes" instead of creating a second deck — *2026-09-29,
      offline headless Edge, scratch copy: IA Module 2 opened, 18 decks before and after, 0 deck
      writes*
- [x] Uploading a revised PDF lists exactly which terms were added or changed — *2026-09-29:
      Module 3 first upload → "First upload"; same file again → "No changes"; a revised copy (new
      SHA-256, same content) built 23 terms → "no term changes". Real added/changed/removed lists
      are covered by tests/server/test_modules.py; not yet seen with a truly revised module.*
- [x] `MODULES.md` is readable by Claude Code and by Claude.ai (upload it, or connect the repo) —
      *2026-09-29: table plus one section per upload, written at the repo root and in DATA_DIR*

---

## Phase 7 — Acceptance, then retire the Claude.ai cards

- [ ] One full day of studying locally with no problems
- [ ] Final verification script run: every count still matches Phase 1's INVENTORY.md
- [ ] Only then stop using the Claude.ai cards. Keep the backup files forever.

---

## Phase 8 — Phone access (Elisha, 2026-09-29)

**Owner:** `backend-builder` (access + PIN) · `frontend-porter` (mobile layout)

- The phone uses the app running on the PC (same database, same Qwen/Claude, nothing to sync),
  over **Tailscale** (private network, works at home and away; nothing opened to the internet).
- A **PIN** is required for any device other than the PC itself. The PC stays PIN-free.
- Every screen works at phone size (360–430 px wide, touch). The desktop layout is unchanged.

**Done when:**
- [ ] With `PHONE_ACCESS=off` (default) the server is reachable from this PC only, as before
- [ ] With it on, a phone on the tailnet opens the app, asks for the PIN once, and studies;
      wrong PINs are rate-limited; other networks/devices are refused
- [ ] Every screen (home, deck, study modes, flashcards, study guide, teacher chat, new deck,
      test paper, manage) has no sideways scrolling and usable tap targets at 360 and 390 px
      wide, checked with screenshots
- [ ] Reader tests and server tests still pass; the desktop layout is unchanged
- [ ] Elisha: installs Tailscale on the PC and the phone, runs the firewall step, sets the PIN

---

## Later (optional)

- Per-account sync (the ScholarSync stack: Supabase)
