"""Import Drill backup files (DATA_DIR\\import\\drill-backup-*.json) into drill.db.

    python -m server.importer [--yes] [--no-decisions]   (server stopped)
    POST /api/import                                     (server running; adds only)

What it does, in order (docs/DATA-MIGRATION.md, "How the import works"):
  1. reads every drill-backup-*.json read-only and records its SHA-256;
  2. PLANS, writing nothing: merges the files (oldest `exported` first) into what the
     database holds, then applies Elisha's not-yet-applied decisions
     (DATA_DIR\\import-decisions.json), all in memory, and lists every key that would be
     added or changed, with what changes;
  3. if nothing would be written, stops there: no snapshot, no write;
  4. if an EXISTING key would change, asks for a typed `yes` (CLI; --yes skips the
     prompt). POST /api/import never changes existing keys: it answers 409 with the plan;
  5. snapshots drill.db (if it exists) as backups\\drill-<ts>-pre-import.db, writes the
     merge in one transaction and the decisions in a second (so kv_history keeps the
     untouched imported value); every overwrite goes to kv_history;
  6. re-hashes every backup file and fails loudly if any changed.
Nothing is ever deleted: a plan that would drop any folder, deck, concept, flashcard or
progress record stops the import before anything is written.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db, snapshots

FILE_GLOB = "drill-backup-*.json"
KNOWN_TOP = {"v", "exported", "library", "decks", "prog", "exams", "prefs"}
DAY_MS = 86400000


class ImportError_(Exception):
    """The import stopped. Nothing was written unless the message says otherwise."""


class ConfirmationRequired(ImportError_):
    """Existing data would change and nobody has confirmed it. Nothing was written."""

    def __init__(self, plan: list):
        super().__init__("Existing data would change. Nothing was written. Stop the server "
                         "and run  .venv\\Scripts\\python -m server.importer  to see the plan "
                         "and confirm it.")
        self.plan = plan


class ImportCancelled(ImportError_):
    pass


# ---- exact ports of the legacy app's helpers ----------------------------------------------

def dumps(v) -> str:
    """The text JSON.stringify would produce (checked byte-for-byte against the real backup)."""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def truthy(v) -> bool:
    """JavaScript truthiness for JSON values ([] and {} are truthy in JS)."""
    if v is None or v is False:
        return False
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


_NOT_AZ09 = re.compile(r"[^a-z0-9]")


def norm(s) -> str:
    """legacy: const norm = s => (s||"").toLowerCase().replace(/[^a-z0-9]/g,"");"""
    return _NOT_AZ09.sub("", str(s if truthy(s) else "").lower())


def merge_deck(mine, theirs):
    """Port of legacy mergeDeck(mine, theirs) (drill-study-app.html, ~line 6834).
    `mine` is the copy already in the database, `theirs` the copy from the backup file.
    (The importer then keeps the database's deck name; see merge_file.)"""
    if not truthy(mine):
        return theirs
    if not truthy(theirs):
        return mine
    base = theirs if len(theirs.get("concepts") or []) > len(mine.get("concepts") or []) else mine
    other = mine if base is theirs else theirs
    out = copy.deepcopy(base)
    out["concepts"] = out.get("concepts") if truthy(out.get("concepts")) else []
    for c in other.get("concepts") or []:
        if not any(x.get("id") == c.get("id") or norm(x.get("name")) == norm(c.get("name"))
                   for x in out["concepts"]):
            out["concepts"].append(copy.deepcopy(c))
    if truthy(other.get("cards")):
        out["cards"] = out.get("cards") if truthy(out.get("cards")) else []
        for k in other["cards"]:
            if not any(x.get("id") == k.get("id") for x in out["cards"]):
                out["cards"].append(copy.deepcopy(k))
    if truthy(other.get("units")) and not truthy(out.get("units")):
        out["units"] = copy.deepcopy(other["units"])
    for k in ("coverage", "source", "context", "adminChoice"):
        if k not in out and k in other:
            out[k] = copy.deepcopy(other[k])
    return out


def badge_counts(entry: dict, deck: dict) -> tuple[int, int]:
    """nCon / nQ exactly as the app computes them: concepts & questions, or for a problem-course
    deck (kind "skill") units & practice problems (legacy ~2493 and ~6202)."""
    if entry.get("kind") == "skill" or deck.get("kind") == "skill":
        units = deck.get("units") or []
        return len(units), sum(len(u.get("practice") or []) for u in units)
    cs = deck.get("concepts") or []
    return len(cs), sum(len(c.get("qs") or []) for c in cs)


# ---- the further-along rule (docs/DATA-MIGRATION.md) ------------------------------------

def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def migrated_view(r: dict, now_ms: float) -> tuple[float, float, float]:
    """(box, right, due) as the app sees the record after legacy migrate() (~line 4035):
    a record without `box` gets box = done ? 2 : 0 and due = done ? now + 3 days : 0.
    Only used to compare; the record itself is stored verbatim."""
    if "box" not in r:
        done = truthy(r.get("done"))
        return (2.0 if done else 0.0), _num(r.get("right")), (now_ms + 3 * DAY_MS if done else 0.0)
    return _num(r.get("box")), _num(r.get("right")), _num(r.get("due"))


def further_along(a: dict, b: dict, a_concepts: int, b_concepts: int,
                  now_ms: float | None = None) -> tuple[str, str]:
    """Compare two records for the same concept. `a` is the one already kept (database).
    Returns (winner, reason) with winner in {"a", "b", "tie"}; "tie" = undecided (same
    deck size), caller keeps `a` and reports it."""
    if dumps(a) == dumps(b):
        return "a", "identical"
    now_ms = time.time() * 1000 if now_ms is None else now_ms
    va, vb = migrated_view(a, now_ms), migrated_view(b, now_ms)
    for i, label in enumerate(("higher box", "more right answers", "later next-review date")):
        if va[i] != vb[i]:
            return ("a" if va[i] > vb[i] else "b"), label
    if a_concepts != b_concepts:
        return ("a" if a_concepts > b_concepts else "b"), "fuller deck copy"
    return "tie", "undecided: box, right, due and deck size all tie"


def _check_prog_shape(p, deck_id: str, side: str) -> None:
    if not isinstance(p, dict):
        raise ImportError_(f"prog:{deck_id}: the {side} copy is not an object "
                           f"({type(p).__name__}). Nothing was written.")
    if "m" in p:
        if not isinstance(p["m"], dict):
            raise ImportError_(f"prog:{deck_id}: the {side} copy's `m` is not an object "
                               f"({dumps(p['m'])[:40]}). Nothing was written.")
        for cid, r in p["m"].items():
            if not isinstance(r, dict):
                raise ImportError_(f"prog:{deck_id}: the {side} copy's record {cid!r} is not "
                                   "an object. Nothing was written.")


def merge_prog(existing, incoming, ex_concepts: int, in_concepts: int, deck_id: str,
               undecided: list, reasons: dict, now_ms: float):
    """Per-concept further-along for `m`; deck-level fields from the side with higher `asked`
    (tie -> existing); a field only one side has is kept. Never drops either side's `m`."""
    if not truthy(incoming):
        return existing
    _check_prog_shape(incoming, deck_id, "file")
    if not truthy(existing):
        return incoming
    _check_prog_shape(existing, deck_id, "database")
    winner = incoming if _num(incoming.get("asked")) > _num(existing.get("asked")) else existing
    out = {}
    keys = list(existing.keys()) + [k for k in incoming.keys() if k not in existing]
    for k in keys:
        if k == "m" and "m" in existing and "m" in incoming:
            em, im = existing["m"], incoming["m"]
            m = {}
            for cid, rec in em.items():
                if cid in im:
                    w, why = further_along(rec, im[cid], ex_concepts, in_concepts, now_ms)
                    if w == "tie":
                        undecided.append((deck_id, cid))
                    if w == "b":
                        reasons[(deck_id, cid)] = f"file record: {why}"
                    m[cid] = copy.deepcopy(im[cid] if w == "b" else rec)
                else:
                    m[cid] = copy.deepcopy(rec)
            for cid, rec in im.items():
                if cid not in em:
                    m[cid] = copy.deepcopy(rec)
            out["m"] = m
        elif k in existing and k in incoming:
            out[k] = copy.deepcopy(winner[k])
        else:
            out[k] = copy.deepcopy(existing[k] if k in existing else incoming[k])
    return out


# ---- reading the files -------------------------------------------------------------------

@dataclass
class BackupFile:
    path: Path
    sha256: str
    size: int
    data: dict
    exported: str
    v: object


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_files(import_dir: Path) -> list[Path]:
    return sorted(p for p in import_dir.glob(FILE_GLOB) if p.is_file())


def read_backup(path: Path) -> BackupFile:
    with open(path, "rb") as fh:              # read-only, binary: the file is never modified
        raw = fh.read()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImportError_(f"{path.name}: not valid UTF-8 JSON ({e}). Nothing was written.")
    if not isinstance(data, dict) or not isinstance(data.get("library"), dict) \
            or not isinstance(data["library"].get("decks"), list):
        raise ImportError_(f"{path.name}: does not look like a Drill backup "
                           "(no library.decks). Nothing was written.")
    unknown = sorted(set(data) - KNOWN_TOP)
    if unknown:
        raise ImportError_(f"{path.name}: unknown top-level keys {unknown}. There is no place "
                           "to keep them without reshaping the data, so nothing was written. "
                           "Ask Elisha / extend the importer.")
    return BackupFile(path=path, sha256=sha, size=len(raw), data=data,
                      exported=str(data.get("exported") or ""), v=data.get("v"))


# ---- in-memory state ---------------------------------------------------------------------

@dataclass
class Report:
    lines: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    added_keys: list = field(default_factory=list)
    changed_keys: list = field(default_factory=list)
    kv_writes: int = 0
    history_rows: int = 0
    snapshot: Path | None = None
    undecided: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    key_status: dict = field(default_factory=dict)

    def say(self, s: str = "") -> None:
        self.lines.append(s)


class State:
    """Key -> JSON text, plus parsed values being changed."""

    def __init__(self, texts: dict):
        self.orig = dict(texts)
        self._cache: dict = {}

    def get(self, key):
        if key not in self._cache:
            self._cache[key] = json.loads(self.orig[key]) if key in self.orig else None
        return self._cache[key]

    def set(self, key, value):
        self._cache[key] = value

    def text(self, key):
        return dumps(self._cache[key]) if key in self._cache else self.orig.get(key)

    def texts(self) -> dict:
        out = dict(self.orig)
        for k, v in self._cache.items():
            if v is not None or k in self.orig:
                out[k] = dumps(v)
        return out


def _write_order(key: str):
    # like the app's restore: deck content first, the library (which lists decks) last
    rank = {"deck": 0, "prog": 1, "exam": 2}.get(key.split(":", 1)[0], 3)
    return (rank + (1 if key == "prefs" else 0) + (2 if key == "library" else 0), key)


def diff(before: dict, after: dict) -> list[tuple[str, str, str]]:
    """(key, new_text, 'added'|'changed') for keys whose text differs, in write order."""
    out = []
    for k in sorted(after, key=_write_order):
        if k not in before:
            out.append((k, after[k], "added"))
        elif before[k] != after[k]:
            out.append((k, after[k], "changed"))
    return out


# ---- the merge ---------------------------------------------------------------------------

def merge_file(state: State, f: BackupFile, rep: Report, reasons: dict, now_ms: float) -> None:
    data = f.data
    lib = state.get("library")
    if lib is None:
        # start from the file's own library object (same key order), folders and decks
        # filled in below exactly as for a merge
        lib = copy.deepcopy(data["library"])
        lib["folders"], lib["decks"] = [], []
    else:
        lib = copy.deepcopy(lib)
        for k, v in data["library"].items():
            if k not in ("folders", "decks") and k not in lib:
                lib[k] = copy.deepcopy(v)
    lib.setdefault("folders", [])
    lib.setdefault("decks", [])

    for f2 in data["library"].get("folders") or []:
        if not any(x.get("id") == f2.get("id") for x in lib["folders"]):
            lib["folders"].append(copy.deepcopy(f2))
            rep.say(f"  library: folder added {f2.get('name')!r} ({f2.get('id')})")

    for meta in data["library"]["decks"]:
        did = meta.get("id")
        deck = (data.get("decks") or {}).get(did)
        if not isinstance(deck, dict) or not isinstance(deck.get("concepts"), list):
            rep.skipped.append((f.path.name, did, meta.get("name")))
            rep.say(f"  SKIPPED deck {meta.get('name')!r} ({did}): no content in the file")
            continue
        key = f"deck:{did}"
        existing = state.get(key)
        ex_n = len((existing or {}).get("concepts") or [])
        merged = merge_deck(existing, deck)
        # like the library entry's name: an import never renames a deck that exists
        if isinstance(existing, dict) and "name" in existing \
                and merged.get("name") != existing["name"]:
            merged["name"] = existing["name"]
        deck_changed = existing is not None and dumps(merged) != dumps(existing)
        if existing is None or deck_changed:
            state.set(key, merged)

        entry = next((e for e in lib["decks"] if e.get("id") == did), None)
        if entry is None:
            entry = copy.deepcopy(meta)
            if not any(x.get("id") == entry.get("folderId") for x in lib["folders"]):
                if not any(x.get("id") == "f-restored" for x in lib["folders"]):
                    lib["folders"].append({"id": "f-restored", "name": "Restored"})
                rep.say(f"  library: {entry.get('name')!r} ({did}) had an unknown folder "
                        f"{entry.get('folderId')!r}; filed under 'Restored' (as Drill does)")
                entry["folderId"] = "f-restored"
            if existing is not None and dumps(merged) != dumps(deck):
                entry["nCon"], entry["nQ"] = badge_counts(entry, merged)
            lib["decks"].append(entry)
        else:
            for k, v in meta.items():          # fill only what is missing; never name/folder
                if k not in entry:
                    entry[k] = copy.deepcopy(v)
            if deck_changed:
                n_con, n_q = badge_counts(entry, merged)
                if entry.get("nCon") != n_con or entry.get("nQ") != n_q:
                    entry["nCon"], entry["nQ"] = n_con, n_q

        incoming = (data.get("prog") or {}).get(did)
        if truthy(incoming):
            pkey = f"prog:{did}"
            ours = state.get(pkey)
            before = len(rep.undecided)
            new = merge_prog(ours, incoming, ex_n, len(deck.get("concepts") or []), did,
                             rep.undecided, reasons, now_ms)
            if ours is None or dumps(new) != dumps(ours):
                state.set(pkey, new)
            if len(rep.undecided) > before:
                rep.say(f"  prog:{did}: {len(rep.undecided) - before} undecided record(s); "
                        "kept the database's")

    if dumps(lib) != (state.text("library") or ""):
        state.set("library", lib)


def check_assertions(state: State, decisions: list) -> None:
    for d in decisions:
        if d.get("type") != "assert_not_in_deck":
            continue
        deck = state.get(f"deck:{d['deck']}") or {}
        names = {norm(n) for n in d["concept_names"]}
        found = [c.get("name") for c in deck.get("concepts") or [] if norm(c.get("name")) in names]
        if found:
            raise ImportError_(f"decision {d['id']}: {found} would be in deck {d['deck']}, which "
                               "Elisha said must not happen. Nothing was written.")


# ---- decisions (planned in memory) --------------------------------------------------------

DATA_DECISIONS = {"rename_deck", "add_folder", "move_deck", "carry_over_progress"}


def load_decisions(path: Path) -> list | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    ds = data.get("decisions")
    if not isinstance(ds, list):
        raise ImportError_(f"{path}: expected a 'decisions' list")
    for d in ds:
        if not d.get("id") or not d.get("type"):
            raise ImportError_(f"{path}: every decision needs an 'id' and a 'type': {d}")
        if d["type"] not in DATA_DECISIONS | {"note", "assert_not_in_deck"}:
            raise ImportError_(f"decision {d['id']}: unknown type {d['type']!r}")
    return ds


def _rec_str(r) -> str:
    if not isinstance(r, dict):
        return "no record"
    return f"box={r.get('box')} right={r.get('right')} due={r.get('due')}"


def _entry(lib, deck_id, did):
    e = next((x for x in lib["decks"] if x.get("id") == deck_id), None)
    if e is None:
        raise ImportError_(f"decision {did}: deck {deck_id} is not in the library. "
                           "Nothing was written.")
    return e


def plan_decisions(state: State, decisions: list, applied: dict, notes_have: set,
                   reasons: dict, rep: Report, now_ms: float):
    """Apply not-yet-applied decisions to `state` (in memory). Returns (new notes, new markers)."""
    new_notes, markers = [], []
    for d in decisions:
        did, typ = d["id"], d["type"]
        if typ == "note":
            new = (d["deck"], d["note"]) not in notes_have
            if new:
                new_notes.append((d["deck"], d["note"], d.get("source")))
            rep.notes.append((d["deck"], d["note"]))
            rep.say(f"  note {d['deck']}: {d['note']!r}"
                    + (" (to record)" if new else " (already recorded)"))
            continue
        if typ == "assert_not_in_deck":
            check_assertions(state, [d])
            rep.say(f"  check {did}: none of {d['concept_names']} is in {d['deck']} - OK")
            rep.decisions.append((did, "checked"))
            continue
        if did in applied:
            rep.say(f"  {did}: already applied {applied[did]}, not applied again")
            rep.decisions.append((did, "already applied"))
            continue

        lib = copy.deepcopy(state.get("library") or {"folders": [], "decks": []})
        if typ == "rename_deck":
            entry = _entry(lib, d["deck"], did)
            deck = copy.deepcopy(state.get(f"deck:{d['deck']}"))
            if deck is None:
                raise ImportError_(f"decision {did}: deck:{d['deck']} not found. Nothing was written.")
            old = entry.get("name")
            entry["name"] = d["name"]
            deck["name"] = d["name"]
            state.set("library", lib)
            state.set(f"deck:{d['deck']}", deck)
            rep.say(f"  {did}: rename {d['deck']} {old!r} -> {d['name']!r} "
                    "(library entry and deck.name)")
        elif typ == "add_folder":
            folder = d["folder"]
            if any(x.get("id") == folder["id"] for x in lib["folders"]):
                rep.say(f"  {did}: folder {folder['id']} already exists")
            else:
                lib["folders"].append(copy.deepcopy(folder))
                state.set("library", lib)
                rep.say(f"  {did}: add folder {folder['name']!r} ({folder['id']}) at the end "
                        f"(position {len(lib['folders'])} of {len(lib['folders'])})")
        elif typ == "move_deck":
            entry = _entry(lib, d["deck"], did)
            if not any(x.get("id") == d["folder"] for x in lib["folders"]):
                raise ImportError_(f"decision {did}: folder {d['folder']} does not exist. "
                                   "Nothing was written.")
            old = entry.get("folderId")
            entry["folderId"] = d["folder"]
            state.set("library", lib)
            rep.say(f"  {did}: move {d['deck']} from folder {old} to {d['folder']}")
        elif typ == "carry_over_progress":
            _carry_over(state, d, rep, reasons, now_ms)
        markers.append((did, json.dumps(d, ensure_ascii=False)))
        rep.decisions.append((did, "applied"))
    return new_notes, markers


def _carry_over(state: State, d: dict, rep: Report, reasons: dict, now_ms: float) -> None:
    src_id, dst_id, fuller = d["from"], d["to"], d["fuller"]
    src_deck, dst_deck = state.get(f"deck:{src_id}"), state.get(f"deck:{dst_id}")
    src_prog, dst_prog = state.get(f"prog:{src_id}"), state.get(f"prog:{dst_id}")
    if not src_deck or not dst_deck or not dst_prog or not isinstance(dst_prog.get("m"), dict):
        raise ImportError_(f"decision {d['id']}: decks/progress for {src_id} -> {dst_id} "
                           "missing. Nothing was written.")
    if src_prog is not None:
        _check_prog_shape(src_prog, src_id, "database")
    dst_prog = copy.deepcopy(dst_prog)
    n_before = len(dst_prog["m"])
    src_m = (src_prog or {}).get("m") or {}
    rep.say(f"  {d['id']}: progress {src_id} -> {dst_id} (fuller copy: {fuller})")
    for name in d["concept_names"]:
        sc = [c for c in src_deck.get("concepts") or [] if norm(c.get("name")) == norm(name)]
        dc = [c for c in dst_deck.get("concepts") or [] if norm(c.get("name")) == norm(name)]
        if len(sc) != 1 or len(dc) != 1:
            raise ImportError_(f"decision {d['id']}: {name!r} matches {len(sc)} concept(s) in "
                               f"{src_id} and {len(dc)} in {dst_id}; expected exactly 1 each. "
                               "Nothing was written.")
        scid, dcid = sc[0]["id"], dc[0]["id"]
        srec, drec = src_m.get(scid), dst_prog["m"].get(dcid)
        if srec is None:
            winner, why = dst_id, f"only {dst_id} has a record"
        elif drec is None:
            winner, why = src_id, f"only {src_id} has a record"
        else:
            # a = destination's record, b = source's; tie-break 4 = the fuller copy
            w, why = further_along(drec, srec, 1 if fuller == dst_id else 0,
                                   1 if fuller == src_id else 0, now_ms)
            winner = src_id if w == "b" else dst_id
        if winner == src_id:
            dst_prog["m"][dcid] = copy.deepcopy(srec)
            reasons[(dst_id, dcid)] = f"carried over from {src_id}/{scid}: {why}"
        rep.say(f"    {name}: {src_id}/{scid} [{_rec_str(srec)}]  vs  {dst_id}/{dcid} "
                f"[{_rec_str(drec)}]  ->  {winner} ({why})")
    n_after = len(dst_prog["m"])
    expect = d.get("expect_to_records")
    if n_after != n_before or (expect is not None and n_after != expect):
        raise ImportError_(f"decision {d['id']}: {dst_id} would have {n_after} progress records "
                           f"(before {n_before}, expected {expect}). Nothing was written.")
    rep.say(f"    {dst_id} progress records: {n_after} (unchanged count); "
            f"{src_id} keeps its own {len(src_m)} records")
    state.set(f"prog:{dst_id}", dst_prog)


# ---- describing and guarding a change ----------------------------------------------------

def _short(v, n=60) -> str:
    s = dumps(v)
    return s if len(s) <= n else s[:n - 3] + "..."


def _match(c, concepts):
    return next((x for x in concepts if x.get("id") == c.get("id")
                 or norm(x.get("name")) == norm(c.get("name"))), None)


def check_no_loss(key: str, old, new) -> None:
    """Stop if a change would drop anything (a bug guard; merges only add)."""
    kind = key.split(":", 1)[0]
    lost = []
    if kind == "deck" and isinstance(old, dict):
        nc = (new or {}).get("concepts") or []
        lost += [f"concept {c.get('name')!r}" for c in old.get("concepts") or []
                 if _match(c, nc) is None]
        ncards = {k.get("id") for k in (new or {}).get("cards") or []}
        lost += [f"card {k.get('id')}" for k in old.get("cards") or [] if k.get("id") not in ncards]
        lost += [f"field {k}" for k in old if k not in (new or {})]
    elif kind == "prog" and isinstance(old, dict):
        nm = (new or {}).get("m") or {}
        lost += [f"record {cid}" for cid in (old.get("m") or {}) if cid not in nm]
        lost += [f"field {k}" for k in old if k not in (new or {})]
    elif key == "library" and isinstance(old, dict):
        nf = {x.get("id") for x in (new or {}).get("folders") or []}
        nd = {x.get("id") for x in (new or {}).get("decks") or []}
        lost += [f"folder {x.get('name')!r}" for x in old.get("folders") or [] if x.get("id") not in nf]
        lost += [f"deck {x.get('name')!r}" for x in old.get("decks") or [] if x.get("id") not in nd]
    if lost:
        raise ImportError_(f"{key}: the planned change would drop {lost}. Nothing was written.")


def describe_change(key: str, old, new, reasons: dict) -> list[str]:
    kind, _, ident = key.partition(":")
    out = []
    if kind == "deck" and isinstance(old, dict) and isinstance(new, dict):
        oc, nc = old.get("concepts") or [], new.get("concepts") or []
        added = [c for c in nc if _match(c, oc) is None]
        if added:
            out.append(f"concepts added ({len(added)}): "
                       + ", ".join(repr(c.get("name")) for c in added))
        replaced = [c for c in oc if (m := _match(c, nc)) is not None and dumps(m) != dumps(c)]
        if replaced:
            out.append(f"concepts whose content becomes the file copy's ({len(replaced)}): "
                       + ", ".join(repr(c.get("name")) for c in replaced))
        ocards = {k.get("id") for k in old.get("cards") or []}
        n_new_cards = sum(1 for k in new.get("cards") or [] if k.get("id") not in ocards)
        if n_new_cards:
            out.append(f"flashcards added: {n_new_cards}")
        for k in list(old) + [k for k in new if k not in old]:
            if k in ("concepts", "cards") or old.get(k, "\0") == new.get(k, "\0"):
                continue
            out.append(f"{k}: {_short(old[k]) if k in old else '(none)'} -> {_short(new.get(k))}")
    elif kind == "prog" and isinstance(old, dict) and isinstance(new, dict):
        om, nm = old.get("m") or {}, new.get("m") or {}
        added = [cid for cid in nm if cid not in om]
        if added:
            out.append(f"progress records added ({len(added)}): {', '.join(added)}")
        for cid in nm:
            if cid in om and dumps(nm[cid]) != dumps(om[cid]):
                out.append(f"record {cid}: [{_rec_str(om[cid])}] -> [{_rec_str(nm[cid])}] "
                           f"({reasons.get((ident, cid), 'replaced')})")
        for k in list(old) + [k for k in new if k not in old]:
            if k == "m" or old.get(k, "\0") == new.get(k, "\0"):
                continue
            out.append(f"deck-level {k}: {_short(old[k]) if k in old else '(none)'} -> "
                       f"{_short(new.get(k))}")
    elif key == "library" and isinstance(old, dict) and isinstance(new, dict):
        of = {x.get("id"): x for x in old.get("folders") or []}
        for x in new.get("folders") or []:
            if x.get("id") not in of:
                out.append(f"folder added: {x.get('name')!r} ({x.get('id')}), at the end")
            elif dumps(x) != dumps(of[x.get("id")]):
                out.append(f"folder {x.get('id')}: {_short(of[x.get('id')])} -> {_short(x)}")
        od = {x.get("id"): x for x in old.get("decks") or []}
        for x in new.get("decks") or []:
            e = od.get(x.get("id"))
            if e is None:
                out.append(f"deck entry added: {x.get('name')!r} ({x.get('id')})")
                continue
            for k in list(e) + [k for k in x if k not in e]:
                if e.get(k, "\0") != x.get(k, "\0"):
                    out.append(f"deck entry {x.get('id')} ({e.get('name')!r}): {k} "
                               f"{_short(e[k]) if k in e else '(none)'} -> {_short(x.get(k))}")
        for k in list(old) + [k for k in new if k not in old]:
            if k not in ("folders", "decks") and old.get(k, "\0") != new.get(k, "\0"):
                out.append(f"{k}: {_short(old.get(k))} -> {_short(new.get(k))}")
    else:
        out.append(f"value {_short(old)} -> {_short(new)}")
    return out or ["(same data, different JSON text)"]


# ---- the database, read only --------------------------------------------------------------

def read_db(db_path: Path):
    """(kv texts, applied decisions, recorded notes, imported file hashes), read-only."""
    if not db_path.exists():
        return {}, {}, set(), set()
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        texts = dict(conn.execute("SELECT key, value FROM kv").fetchall())

        def q(sql):
            try:
                return conn.execute(sql).fetchall()
            except sqlite3.OperationalError:     # table not there yet
                return []
        applied = dict(q("SELECT id, applied_at FROM import_decisions_applied"))
        notes = {(a, b) for a, b in q("SELECT deck_id, note FROM import_notes")}
        files = {r[0] for r in q("SELECT sha256 FROM import_files")}
    finally:
        conn.close()
    return texts, applied, notes, files


def deck_table(texts: dict) -> list[str]:
    lib = json.loads(texts.get("library", "null")) or {"folders": [], "decks": []}
    folders = {f.get("id"): f.get("name") for f in lib.get("folders") or []}
    out = [f"  {'#':>2}  {'deck':<26} {'id':<14} {'folder':<30} {'conc':>5} {'qs':>5} "
           f"{'cards':>5} {'guide':>5} {'units':>5} {'prog':>5}"]
    tot = [0] * 6
    for i, e in enumerate(lib.get("decks") or [], 1):
        deck = json.loads(texts.get(f"deck:{e.get('id')}", "null")) or {}
        prog = json.loads(texts.get(f"prog:{e.get('id')}", "null")) or {}
        cs = deck.get("concepts") or []
        n = [len(cs), sum(len(c.get("qs") or []) for c in cs), len(deck.get("cards") or []),
             sum(1 for c in cs if truthy(c.get("guide"))), len(deck.get("units") or []),
             len(prog.get("m") or {})]
        tot = [a + b for a, b in zip(tot, n)]
        out.append(f"  {i:>2}  {str(e.get('name'))[:26]:<26} {str(e.get('id')):<14} "
                   f"{str(folders.get(e.get('folderId'), '?'))[:30]:<30} "
                   + " ".join(f"{x:>5}" for x in n))
    out.append(f"      {'TOTAL (' + str(len(lib.get('decks') or [])) + ' decks)':<72}"
               + " ".join(f"{x:>5}" for x in tot))
    return out


# ---- run ---------------------------------------------------------------------------------

def run_import(settings, confirm=None, apply_decisions_step: bool = True) -> Report:
    """confirm: None -> refuse to change existing keys (raise ConfirmationRequired);
    a callable(report) -> bool is asked (after the plan is in report.lines) when existing
    keys would change. Adding keys never needs confirmation."""
    rep = Report()
    files_paths = find_files(settings.import_dir)
    if not files_paths:
        raise ImportError_(f"No {FILE_GLOB} files in {settings.import_dir}. Nothing was written.")
    files = [read_backup(p) for p in files_paths]
    files.sort(key=lambda f: (f.exported, f.path.name))
    rep.say(f"Backup files ({len(files)}), oldest exported first:")
    for f in files:
        rep.say(f"  {f.path.name}  v={f.v}  exported={f.exported}  {f.size:,} bytes  "
                f"sha256={f.sha256}")
    decisions = load_decisions(settings.decisions_file) if apply_decisions_step else None
    now_ms = time.time() * 1000

    with db.WRITE_LOCK:
        existed = settings.db_path.exists()
        db_texts, applied, notes_have, files_have = read_db(settings.db_path)
        rep.say("")
        rep.say("Merge (planned; nothing written yet):")
        reasons: dict = {}
        merged = State(db_texts)
        for f in files:
            rep.say(f" {f.path.name}:")
            merge_file(merged, f, rep, reasons, now_ms)
        # unfinished Test papers: only where the database has none; newest file first
        for f in sorted(files, key=lambda f: (f.exported, f.path.name), reverse=True):
            for eid, draft in (f.data.get("exams") or {}).items():
                if truthy(draft) and not truthy(merged.get(f"exam:{eid}")):
                    merged.set(f"exam:{eid}", draft)
        # settings: only if the database has none; from the newest v2 file
        v2 = [f for f in files if f.v == 2 and truthy(f.data.get("prefs"))]
        if v2 and not truthy(merged.get("prefs")):
            newest = max(v2, key=lambda f: (f.exported, f.path.name))
            merged.set("prefs", newest.data["prefs"])
            rep.say(f"  prefs from {newest.path.name}")
        if decisions:
            check_assertions(merged, decisions)
        merged_texts = merged.texts()

        decided = State(merged_texts)
        new_notes, markers = [], []
        rep.say("")
        if decisions is None:
            rep.say("Decisions: " + ("skipped (--no-decisions)" if not apply_decisions_step
                                     else f"no file at {settings.decisions_file}, none applied"))
        else:
            rep.say(f"Decisions ({settings.decisions_file}):")
            new_notes, markers = plan_decisions(decided, decisions, applied, notes_have,
                                                reasons, rep, now_ms)
        final_texts = decided.texts()

        merge_changes = diff(db_texts, merged_texts)
        decision_changes = diff(merged_texts, final_texts)
        overall = diff(db_texts, final_texts)
        new_files = [f for f in files if f.sha256 not in files_have]
        for key, text, status in overall:
            if status == "changed":
                check_no_loss(key, json.loads(db_texts[key]), json.loads(text))

        # the plan
        touched = set()
        for f in files:
            d = f.data
            touched |= {"library"} | {f"deck:{m.get('id')}" for m in d["library"]["decks"]
                                      if isinstance((d.get("decks") or {}).get(m.get("id")), dict)}
            touched |= {f"prog:{k}" for k, v in (d.get("prog") or {}).items() if truthy(v)}
            touched |= {f"exam:{k}" for k, v in (d.get("exams") or {}).items() if truthy(v)}
            if truthy(d.get("prefs")):
                touched.add("prefs")
        status = {k: "unchanged" for k in touched}
        status.update({k: ("added" if s == "added" else "merged") for k, _, s in overall})
        rep.key_status = status
        rep.added_keys = [k for k, _, s in overall if s == "added"]
        rep.changed_keys = [k for k, _, s in overall if s == "changed"]
        plan = ["", f"Plan: {len(rep.added_keys)} keys to add, {len(rep.changed_keys)} existing "
                    f"keys to change, {sum(1 for v in status.values() if v == 'unchanged')} "
                    "unchanged"]
        if rep.added_keys:
            plan.append("  Add (no existing data touched): " + ", ".join(rep.added_keys))
        for key in rep.changed_keys:
            plan.append(f"  CHANGE {key}:")
            for line in describe_change(key, json.loads(db_texts[key]),
                                        json.loads(final_texts[key]), reasons):
                plan.append(f"      {line}")
        pending = [d for d, s in rep.decisions if s == "applied"]
        if pending:
            plan.append(f"  Decisions to apply now (once only): {', '.join(pending)}")
        if new_files or new_notes:
            plan.append(f"  Bookkeeping: {len(new_files)} backup file(s) to record, "
                        f"{len(new_notes)} note(s) to record")
        if rep.undecided:
            plan.append(f"  UNDECIDED progress records (the database's is kept): {rep.undecided}")
        rep.plan = plan
        rep.lines.extend(plan)

        nothing = not overall and not new_files and not new_notes and not markers
        if nothing:
            rep.say("Nothing to write: the database already holds all of it. No snapshot taken.")
        else:
            # a pending decision that touches existing data shows up as a changed key
            if rep.changed_keys:
                if confirm is None:
                    raise ConfirmationRequired(plan)
                if not confirm(rep):
                    raise ImportCancelled("Not confirmed. Nothing was written.")
            if existed:
                rep.snapshot = snapshots.take_snapshot(settings, tag="pre-import")
                rep.say(f"Snapshot before writing: {rep.snapshot}")
            else:
                rep.say(f"No database yet; creating {settings.db_path}")
            db.init_db(settings.db_path)
            conn = db.connect(settings.db_path)
            try:
                hist0 = conn.execute("SELECT COUNT(*) FROM kv_history").fetchone()[0]
                ts = db.now_iso()
                with db.transaction(conn):
                    now_texts = dict(conn.execute("SELECT key, value FROM kv").fetchall())
                    if any(now_texts.get(k) != db_texts.get(k) for k, _, _ in overall):
                        raise ImportError_("The database changed while the import was being "
                                           "planned. Nothing was written; run it again.")
                    for key, text, _ in merge_changes:
                        db.put_in_tx(conn, key, text, ts)
                        rep.kv_writes += 1
                    for f in new_files:
                        conn.execute("INSERT OR IGNORE INTO import_files(sha256, name, size, "
                                     "exported, first_imported_at) VALUES(?,?,?,?,?)",
                                     (f.sha256, f.path.name, f.size, f.exported, ts))
                with db.transaction(conn):
                    for key, text, _ in decision_changes:
                        db.put_in_tx(conn, key, text, ts)
                        rep.kv_writes += 1
                    for deck_id, note, source in new_notes:
                        conn.execute("INSERT OR IGNORE INTO import_notes(deck_id, note, source, "
                                     "created_at) VALUES(?,?,?,?)", (deck_id, note, source, ts))
                    for did, detail in markers:
                        conn.execute("INSERT INTO import_decisions_applied(id, detail, "
                                     "applied_at) VALUES(?,?,?)", (did, detail, ts))
                rep.history_rows = (conn.execute("SELECT COUNT(*) FROM kv_history").fetchone()[0]
                                    - hist0)
            finally:
                conn.close()
            db.checkpoint(settings.db_path)
            rep.say(f"Written: {len(merge_changes)} key(s) from the files, then "
                    f"{len(decision_changes)} key(s) by decisions.")

    after_texts, _, notes_now, _ = read_db(settings.db_path)
    rep.say("")
    rep.say("Import notes on record (not app data):")
    for deck_id, note in sorted(notes_now, key=lambda x: (x[1], x[0])):
        rep.say(f"  {deck_id}: {note}")
    if not notes_now:
        rep.say("  none")
    rep.say("")
    rep.say("Per deck, in the database now:")
    rep.lines.extend(deck_table(after_texts))

    # the backup files must be byte-for-byte what they were
    rep.say("")
    bad = []
    for f in files:
        after = sha256_of(f.path)
        ok = after == f.sha256
        rep.say(f"Backup file unchanged: {f.path.name} sha256 before={f.sha256[:16]}... "
                f"after={after[:16]}... {'OK' if ok else 'CHANGED!'}")
        if not ok:
            bad.append(f.path.name)
    rep.say("")
    rep.say(f"Summary: {rep.kv_writes} kv writes, {rep.history_rows} kv_history rows added, "
            f"{len(rep.skipped)} decks skipped, {len(rep.undecided)} undecided progress "
            f"records, snapshot: {rep.snapshot.name if rep.snapshot else 'none'}.")
    if bad:
        raise ImportError_(f"BACKUP FILES CHANGED DURING IMPORT: {bad}")
    return rep


def main(argv=None) -> int:
    import argparse
    from .instance_lock import AlreadyRunning, InstanceLock
    from .settings import SettingsError, load_settings

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m server.importer",
                                 description="Import DATA_DIR\\import\\drill-backup-*.json")
    ap.add_argument("--yes", action="store_true",
                    help="do not ask before changing existing data (for scripts)")
    ap.add_argument("--user", metavar="EMAIL",
                    help="import into this account's own database (Phase 9); "
                         "default: DATA_DIR itself, as before")
    ap.add_argument("--no-decisions", action="store_true",
                    help="merge the files only; do not apply import-decisions.json")
    args = ap.parse_args(argv)
    printed = 0

    def ask(rep: Report) -> bool:
        nonlocal printed
        print("\n".join(rep.lines))
        printed = len(rep.lines)
        if args.yes:
            print("--yes given: changing existing data without asking.")
            return True
        try:
            answer = input("Existing data will change as listed above (the old values are kept "
                           "in kv_history and a snapshot is taken first).\n"
                           "Type yes to go ahead: ")
        except EOFError:
            answer = ""
        return answer.strip() == "yes"

    from .accounts import AccountError, settings_for_email
    try:
        settings = settings_for_email(load_settings(), args.user)
        print(f"DATA_DIR = {settings.data_dir}")
        if not settings.is_main_data:
            print(f"Account {args.user}: {settings.root}")
        with InstanceLock(settings.lock_file, "importer"):
            rep = run_import(settings, confirm=ask,
                             apply_decisions_step=not args.no_decisions)
    except ImportCancelled as e:
        print(f"IMPORT CANCELLED: {e}")
        return 1
    except (SettingsError, AlreadyRunning, ImportError_, AccountError) as e:
        print(f"IMPORT STOPPED: {e}")
        return 2
    print("\n".join(rep.lines[printed:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
