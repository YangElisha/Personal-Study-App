# CHANGELOG

Newest first. Every change gets an entry in the same commit.

## [Unreleased]

### Added
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
- Phase 1 done: `DATA_DIR\import\INVENTORY.md` built from the backup `drill-backup-2026-09-28.json`
  (18 decks, 506 concepts, 1,859 questions, 506 flashcards, 217 progress records). Nothing
  was imported. Elisha's import decisions are recorded in INVENTORY.md:
  - "IA Module 3": `mui02dwojkee` is the real deck; `muaicdxx9pud` is archived as
    "IA Module 3 (old build)" and progress on matching concept names carries over.
  - NLP Modules 2 and 3 are to be rebuilt from their PDFs after Phase 4.
  - The same-named Module 1/2 decks stay separate and are marked "rename later".

### Found, not fixed
- The two fixtures are saved in different shapes: `module2-text.json` is
  `{page: {items, imgs}}`, `module3-text.json` is `{page: [items]}` with no picture
  count. The test accepts both and takes a missing count as 0, so for Module 3 it cannot
  tell a title-over-a-picture slide from a divider. Fixtures left unchanged (Elisha,
  2026-09-28). **When Module 3's fixture is re-captured from the PDF:** check whether its
  title-only divider slides start being classed as picture slides because of Canva
  full-slide background images. If they do, the reader needs a fix to tell full-slide
  backgrounds from real pictures.
