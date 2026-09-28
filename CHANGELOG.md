# CHANGELOG

Newest first. Every change gets an entry in the same commit.

## [Unreleased]

### Added
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

### Migration
- Phase 1 done: `DATA_DIR\import\INVENTORY.md` built from the backup `drill-backup-2026-09-28.json`
  (18 decks, 506 concepts, 1,859 questions, 506 flashcards, 217 progress records). Nothing
  was imported. Elisha's import decisions are recorded in INVENTORY.md:
  - "IA Module 3": `mui02dwojkee` is the real deck; `muaicdxx9pud` is archived as
    "IA Module 3 (old build)" and progress on matching concept names carries over.
  - NLP Modules 2 and 3 are to be rebuilt from their PDFs after Phase 4.
  - The same-named Module 1/2 decks stay separate and are marked "rename later".

### Found, not fixed
- (nothing yet)
