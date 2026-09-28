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
      Not covered: neither fixture has an activity slide, so a break that stops activity
      slides being set aside still passes.*

---

## Phase 3 — Local server and database

**Owner:** `backend-builder`

- A small local server (see ARCHITECTURE.md) that
  - stores what Drill stores, in SQLite at `DATA_DIR\drill.db`
  - snapshots the database to `DATA_DIR\backups\` on start and daily, keeping 30
  - serves the app at `http://localhost:8765`, started by double-clicking `start.bat`
  - imports the backup files from `DATA_DIR\import\`

**Done when:**
- [ ] Import of every backup file succeeds
- [ ] A verification script prints, per deck, *expected vs found* for concepts, questions,
      flashcards and progress records — and every row matches
- [ ] Importing the same file twice changes nothing (merge, never duplicate)
- [ ] Where two cards had the same deck, no concept from either copy is missing
- [ ] Restarting the server creates a snapshot in `DATA_DIR\backups\`, and restoring one works

---

## Phase 4 — Run the app locally

**Owner:** `frontend-porter`

- Copy `legacy/drill-study-app.html` to `app/index.html`
- Replace **only** the storage layer and the AI call
- Vendor pdf.js and the fonts so nothing loads from the internet

**Done when:**
- [ ] With Wi-Fi **off**: the app opens, every imported deck is there, a study session
      saves progress, and reopening the browser keeps it
- [ ] Building a deck from `modules/MODULE3_S-ITCS318.pdf` with Wi-Fi off gives the same
      23 terms (this path needs no AI)
- [ ] Phase 2 tests still pass against `app/index.html`

---

## Phase 5 — Qwen by default, Claude when online (no API key)

**Owner:** `ai-router`

- One endpoint the app calls. Qwen through Ollama by default; when online and
  `CLAUDE_CLI=on`, text requests go to the official `claude -p`. It always answers in the
  shape the app already expects.
- A small badge in the app shows which model answered.

**Done when:**
- [ ] Online: teacher chat and essay marking answer via Claude (`claude -p`)
- [ ] Wi-Fi off: the same features answer via Qwen, with no change in the app
- [ ] `CLAUDE_CLI=off`: everything answers via Qwen
- [ ] A prompt longer than 32,000 characters reaches `claude -p` whole (sent on stdin)
- [ ] A prompt near the context limit reaches Qwen **whole**, or is refused loudly
- [ ] A picture slide (Module 2, slide 24) is read by Qwen
- [ ] `ollama ps` shows 100% GPU during a long request

---

## Phase 6 — Module library and change log

**Owner:** `backend-builder`

- Every uploaded module is saved in `DATA_DIR\modules\`, fingerprinted, and recorded in the database
  with its coverage report
- `MODULES.md` is regenerated: each module, its deck, term count, date, and what changed
  since the last upload
- App changes are recorded in `CHANGELOG.md`

**Done when:**
- [ ] Uploading Module 2 again reports "no changes" instead of creating a second deck
- [ ] Uploading a revised PDF lists exactly which terms were added or changed
- [ ] `MODULES.md` is readable by Claude Code and by Claude.ai (upload it, or connect the repo)

---

## Phase 7 — Acceptance, then retire the Claude.ai cards

- [ ] One full day of studying locally with no problems
- [ ] Final verification script run: every count still matches Phase 1's INVENTORY.md
- [ ] Only then stop using the Claude.ai cards. Keep the backup files forever.

---

## Later (optional)

- Phone access (GitHub Pages or local network)
- Per-account sync (the ScholarSync stack: Supabase)
