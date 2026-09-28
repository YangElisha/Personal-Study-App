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
  Limit: neither fixture has an activity slide, so a break that stops `setAsideActivities`
  setting aside real activities still passes; that needs a fixture with an activity slide.
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
