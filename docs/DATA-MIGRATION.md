# DATA MIGRATION — getting everything out of Drill with nothing lost

## What Drill's backup contains

| Included | Not included |
|---|---|
| Every folder and its colour | Teacher chat history (Drill never saves it) |
| Every deck: concepts, questions, flashcards, topics | The original PDFs (Drill never stores them) |
| Study-guide explanations you had written | |
| Coverage reports, source text, problem courses | |
| All progress: review schedule, streaks, lessons passed | |
| **Settings** and **unfinished Test papers** — newest card only (backup v2) | |

Older cards make v1 backups without settings — that's fine, your current settings are in
the newest card.

## The trap: each Drill card has its own storage

Every time Drill was rebuilt, Claude.ai made a new app card, and each card keeps its own
separate storage. Your decks are spread across several cards — which is why your sidebar
shows two "IA Module 3" decks with different counts.

**So: back up every card you have used, not just the newest one.**

## Steps

1. For each Drill card, oldest to newest:
   - Manage → **Download a backup** → **Copy**
   - Paste into Notepad and save as `DATA_DIR\import\drill-backup-<anything>.json`
     (any `drill-backup-*.json` name; Save as type: **All files**, Encoding: **UTF-8**), one file per card
2. Put the module PDFs into `DATA_DIR\modules\`.
3. Ask `migration-guardian` to build `DATA_DIR\import\INVENTORY.md`.
4. Check INVENTORY.md yourself. Anything missing → find the card that has it, repeat step 1.

## How duplicates are resolved

The same deck in two cards is matched by its id. The **fuller copy** is the base, every
concept only the other copy has is added, and the **further-along progress** is kept.

**"Further-along" for one concept's progress record** — compare the two records in order:

1. **Higher box** wins.
2. If the boxes are tied: **more right answers** wins.
3. If still tied: the **later next-review date** (`due`) wins.

**How this differs from Drill's own restore.** Drill's restore (`mergeDeck` and
`applyBackup` in the legacy app) merges deck *content* the same way: the copy with more
concepts is the base, concepts only the other copy has (matched by id or name) and
flashcards only the other copy has (matched by id) are added, and coverage, source text
and the other extras are filled in only where missing, so a restore can never shrink a
deck. It does **not** compare progress concept by concept. It keeps one side's progress
record for the whole deck: the backup's, if its total of questions answered (`asked`) is
at least as high as the app's, otherwise the app's. The import here chooses per concept,
using the rule above.

Two different decks with the same name are both kept and flagged in INVENTORY.md for you
to decide.

## What makes it "no mistakes"

- Backup files in `DATA_DIR\import\` are **never modified**.
- The import only adds; it never deletes.
- A verification script compares, deck by deck, the counts in the backup files with the
  counts in the database, and prints every row. Any mismatch stops the migration.
- The Claude.ai cards stay untouched until Phase 7, so there is always a second copy.
