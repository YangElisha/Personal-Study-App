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

**"Further-along" for one concept's progress record.** If only one copy has a record for
the concept, that record is kept. If both do, compare them in order:

1. **Higher box** wins.
2. If the boxes are tied: **more right answers** wins.
3. If still tied: the **later next-review date** (`due`) wins.
4. If still tied: the record from the **fuller deck copy** (more concepts) is kept.

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

## How the import works (Phase 3, `server/importer.py`)

Run `.venv\Scripts\python -m server.importer` while the server is stopped. With the server
running, `POST /api/import` does the same but only ever **adds** keys (see step 3); reload
the app afterwards.

1. **Read.** Every `DATA_DIR\import\drill-backup-*.json` is opened read-only and its SHA-256
   recorded. A file that is not valid JSON, has no `library.decks`, or has a top-level key
   other than `v, exported, library, decks, prog, exams, prefs` stops the import before
   anything is written (there would be nowhere to keep that key without reshaping data).
2. **Plan, writing nothing.** The files are merged (rules below), oldest `exported` first,
   into what the database holds, and Elisha's not-yet-applied decisions are applied on top,
   all in memory. The plan lists the keys to **add**, every **existing key that would
   change** with what changes (concepts added, concepts whose content becomes the file
   copy's, flashcards added, progress records replaced and by which tie-break, deck-level
   progress fields, `nCon`/`nQ`, folders and library entries), the unchanged keys, and the
   decisions that would be applied now. A plan that would drop any folder, deck, concept,
   flashcard or progress record stops the import (a guard; the rules only add).
3. **Ask before changing existing data** (CLAUDE.md rule 2). Adding keys needs no
   confirmation: it only adds data. If any **existing** key would change, the CLI prints
   the plan and goes ahead only after a typed `yes` (`--yes` skips the prompt, for scripts);
   anything else, or no terminal, cancels with nothing written. `POST /api/import` never
   changes an existing key: it answers **409** `confirmation_required` with the plan and
   asks for the CLI with the server stopped. A pending decision that would change existing
   data shows up as a changed key, so it is confirmed the same way.
4. **Write**, only if there is something to write. If nothing would change, the import
   stops there: no write and **no snapshot**. Otherwise `drill.db` (if it exists) is first
   copied to `backups\drill-<ts>-pre-import.db` (never pruned). The merge is written in one
   transaction, then the decisions in a second, so on a first import `kv_history` holds the
   untouched imported value of anything a decision changed. Every overwrite goes to
   `kv_history`. If the database changed between planning and writing, nothing is written.

Merge rules. Keys are Drill's own (`library`, `deck:<id>`, `prog:<id>`, `prefs`,
`exam:<id>`); each value is written as the exact text `JSON.stringify` gives (checked
byte-for-byte on the real backup).

- **Folders:** matched by id. Existing folders keep their order and colour; new ones are
  appended in file order. None is ever removed.
- **Library entries:** matched by id; new ones appended. An existing entry's `name` and
  `folderId` are **never** changed by an import (Drill's own restore overwrites the name;
  we don't, so Elisha's renames stick). Fields an entry lacks are filled in. If the merge
  changed the deck, `nCon`/`nQ` are recomputed the way the app does (concepts and
  questions; units and practice problems for a `kind:"skill"` deck). A new deck whose
  folder does not exist goes into a "Restored" folder, as Drill does.
- **Deck content:** Drill's `mergeDeck`, ported exactly (the copy already in the database
  is the base on a tie), with one deliberate difference: an existing deck's `name` is kept
  even when the file copy is the base, for the same reason as the library entry. A deck the
  file lists but holds no content for is skipped and reported.
- **Progress, per concept:** the further-along rule above. "The fuller deck copy" means the
  database's copy of the deck versus the file's copy, before the merge. Records are
  compared as the app reads them after its `migrate()` (a record without `box` counts as
  box 2 and due in 3 days if `done`, else box 0 and due 0); the record itself is stored
  verbatim. Identical records are left alone. If every tie-break ties and both copies have
  the same number of concepts, the database record is kept and the case is listed as
  **UNDECIDED**. If either side's progress or its `m` is not an object (or a record in it
  isn't), the import stops with nothing written, so neither side's `m` can be lost.
- **Progress, deck-level fields** (`asked`, `right`, `sessions`, `last`, `teach`, `course`
  and any others) — *implementation choice, Phase 3:* a field only one side has is kept;
  for fields both sides have, the side with the higher `asked` wins as a group, and a tie
  keeps the database's. This follows Drill's own restore, which also chooses by `asked`,
  with one difference: Drill gives a tie to the backup (`>=`); the import gives it to the
  database, the conservative choice (nothing already there is replaced on a tie).
- **prefs:** written only if the database has none, from the newest v2 file.
- **exam:<id>:** written only if the database has none; newest file first.

**Decisions** (Elisha's, from `DATA_DIR\import-decisions.json`, kept out of the repo and
out of `import\`). Each decision that changes data runs **once**, is recorded in the table
`import_decisions_applied`, and is never re-applied, so a later rename or move in the app
is not undone by re-running the import. Checks (`assert_not_in_deck`) run every time. A
failing check or decision stops the whole import with nothing written. Decision types:

| `type` | Fields | Effect |
|---|---|---|
| `rename_deck` | `deck`, `name` | library entry `name` and `deck.name` |
| `add_folder` | `folder` `{id,name}` | appended at the end of `library.folders` |
| `move_deck` | `deck`, `folder` | library entry `folderId` |
| `assert_not_in_deck` | `deck`, `concept_names` | stop if any is in the deck (`norm` match) |
| `carry_over_progress` | `from`, `to`, `fuller`, `concept_names`, `expect_to_records` | for each name (exactly one `norm` match in each deck), the further-along record of the two is written under the `to` concept id; `from` keeps its records; the `to` record count must not change |
| `note` | `deck`, `note`, `source` | a row in table `import_notes` (not app data) |

**Report:** the plan, each decision, the notes, per-deck counts (concepts, questions,
flashcards, study-guide entries, problem courses, progress records) read back from the
database, and the SHA-256 of every backup file before and after (the import fails loudly if
one changed).

Running the import again with the same files writes nothing and takes no snapshot: 0 kv
writes, 0 history rows, no question asked.

**Re-running after studying locally:** the import merges like Drill's restore, so it can
change data studied since. A deck deleted in the app would come back, but that also changes
`library`, so it is asked about too: whenever a key that already exists would change, the
import stops and shows the plan first. For example, a deck whose concepts were deleted in the app would be merged with
the fuller file copy, or a progress record the file has further along would replace the
one in the database. Nothing changes until Elisha types `yes`. The replaced values then go
to `kv_history` and a pre-import snapshot, so even a confirmed import loses nothing. Only
re-run the import when there is a new backup file to bring in.

## What makes it "no mistakes"

- Backup files in `DATA_DIR\import\` are **never modified**.
- The import only adds; it never deletes.
- A verification script compares, deck by deck, the counts in the backup files with the
  counts in the database, and prints every row. Any mismatch stops the migration.
- The Claude.ai cards stay untouched until Phase 7, so there is always a second copy.
