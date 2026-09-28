"""Verify that the Drill backup files are in drill.db, losslessly.

Independent of server/importer.py on purpose: nothing is imported from server/. The counts
follow INVENTORY.md's definitions, the merge follows docs/DATA-MIGRATION.md and the legacy
app's mergeDeck, written again here from those documents.

Read-only: the database is opened with the sqlite URI mode=ro (plus PRAGMA query_only),
the backup files, INVENTORY.md and import-decisions.json are opened 'rb'. Nothing is written
anywhere. (SQLite itself may create the usual drill.db-wal / drill.db-shm side files next to
a WAL database when it is opened; they hold no data of ours.)

Usage (from the repo folder):
    .venv\\Scripts\\python tools\\verify_import.py                 # DATA_DIR from .env
    .venv\\Scripts\\python tools\\verify_import.py --data-dir D:\\x  # another DATA_DIR
    .venv\\Scripts\\python tools\\verify_import.py --after-study     # Phase 7

Default mode ("exact", right after an import): the database must hold exactly what the
backup files hold, merged by deck id as DATA-MIGRATION.md describes, with Elisha's decisions
(DATA_DIR\\import-decisions.json) applied, and nothing else.

--after-study (Phase 7, after studying locally): every deck, concept, question, flashcard,
study-guide entry, problem and progress record from the backup files must still be there;
more is allowed (new progress, new decks). Content edits are listed, not failed.

Exit code: 0 = every check passed, 1 = at least one mismatch, 2 = could not run.
"""
from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------------------
# small helpers


def read_env_data_dir() -> str | None:
    if os.environ.get("DATA_DIR"):
        return os.environ["DATA_DIR"]
    env = REPO_ROOT / ".env"
    if not env.is_file():
        return None
    with open(env, "rb") as fh:
        text = fh.read().decode("utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == "DATA_DIR":
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return None


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(s) -> str:
    """Drill's name match: lower-case, keep a-z and 0-9 only."""
    return re.sub(r"[^a-z0-9]", "", (s if isinstance(s, str) else "").lower())


def short(v, n=70) -> str:
    t = json.dumps(v, ensure_ascii=False)
    return t if len(t) <= n else t[: n - 3] + "..."


def num(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    return v


def kind(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def diff(a, b, path="", out=None, order=True):
    """Every difference between a (expected) and b (database), as readable lines.
    Strict about types (true is not 1). JSON numbers 1 and 1.0 are the same value, as in JS.
    order=True also reports objects whose keys are in a different order (that changes the
    exact text JSON.stringify gives)."""
    if out is None:
        out = []
    ka, kb = kind(a), kind(b)
    if ka != kb:
        out.append(f"{path or '(value)'}: expected {short(a)} ({ka}), found {short(b)} ({kb})")
        return out
    if ka == "object":
        for k in a:
            if k not in b:
                out.append(f"{path}.{k}: missing in database (expected {short(a[k])})")
        for k in b:
            if k not in a:
                out.append(f"{path}.{k}: extra in database ({short(b[k])})")
        common_a = [k for k in a if k in b]
        common_b = [k for k in b if k in a]
        if order and common_a != common_b:
            out.append(f"{path or '(object)'}: key order differs: expected {common_a[:8]}, "
                       f"found {common_b[:8]}")
        for k in common_a:
            diff(a[k], b[k], f"{path}.{k}", out, order)
    elif ka == "array":
        for i in range(max(len(a), len(b))):
            label = f"{path}[{i}]"
            item = a[i] if i < len(a) else b[i]
            if isinstance(item, dict) and "id" in item:
                label += f"(id={item['id']})"
            if i >= len(a):
                out.append(f"{label}: extra in database ({short(b[i])})")
            elif i >= len(b):
                out.append(f"{label}: missing in database (expected {short(a[i])})")
            else:
                diff(a[i], b[i], label, out, order)
    else:
        if a != b:
            out.append(f"{path or '(value)'}: expected {short(a)}, found {short(b)}")
    return out


def same(a, b, order=False) -> bool:
    return not diff(a, b, order=order)


# ---------------------------------------------------------------------------------------
# counting, as INVENTORY.md defines it


def counts(deck, prog, entry) -> dict:
    deck = deck if isinstance(deck, dict) else {}
    cs = deck.get("concepts") if isinstance(deck.get("concepts"), list) else []
    units = deck.get("units") if isinstance(deck.get("units"), list) else []
    m = prog.get("m") if isinstance(prog, dict) and isinstance(prog.get("m"), dict) else {}
    return {
        "concepts": len(cs),
        "questions": sum(len(c.get("qs") or []) for c in cs),
        "cards": len(deck.get("cards") or []),
        "guide": sum(1 for c in cs if isinstance(c.get("guide"), str) and c.get("guide") != ""),
        "courses": len(units),
        "problems": sum(len(u.get("practice") or []) for u in units),
        "records": len(m),
        "folder": (entry or {}).get("folderId"),
    }


def badge(deck) -> tuple[int, int]:
    """nCon / nQ the way the app computes them (skill decks count units and problems)."""
    if deck.get("kind") == "skill":
        units = deck.get("units") or []
        return len(units), sum(len(u.get("practice") or []) for u in units)
    cs = deck.get("concepts") or []
    return len(cs), sum(len(c.get("qs") or []) for c in cs)


# ---------------------------------------------------------------------------------------
# the expected state, from the backup files (DATA-MIGRATION.md, written again here)


def further_along(a, b, a_fuller, b_fuller):
    """Return ('a'|'b'|'same'|'undecided', reason) for two progress records of one concept."""
    if same(a, b):
        return "same", "identical records"
    for key, label in (("box", "higher box"), ("right", "more right answers"),
                       ("due", "later next-review date")):
        va, vb = num((a or {}).get(key)), num((b or {}).get(key))
        if va != vb:
            return ("a" if va > vb else "b"), f"{label} ({key} {va} vs {vb})"
    if a_fuller and not b_fuller:
        return "a", "all tied; fuller deck copy"
    if b_fuller and not a_fuller:
        return "b", "all tied; fuller deck copy"
    return "undecided", "all tied, same size"


def merge_deck(mine, theirs):
    """legacy mergeDeck: fuller copy is the base (tie: mine), add what only the other has."""
    if not mine:
        return copy.deepcopy(theirs)
    if not theirs:
        return copy.deepcopy(mine)
    base, other = (theirs, mine) if len(theirs.get("concepts") or []) > len(
        mine.get("concepts") or []) else (mine, theirs)
    out = copy.deepcopy(base)
    out["concepts"] = out.get("concepts") or []
    for c in other.get("concepts") or []:
        if not any(x.get("id") == c.get("id") or norm(x.get("name")) == norm(c.get("name"))
                   for x in out["concepts"]):
            out["concepts"].append(copy.deepcopy(c))
    if other.get("cards"):
        out["cards"] = out.get("cards") or []
        for k in other["cards"]:
            if not any(x.get("id") == k.get("id") for x in out["cards"]):
                out["cards"].append(copy.deepcopy(k))
    if other.get("units") and not out.get("units"):
        out["units"] = copy.deepcopy(other["units"])
    for k in ("coverage", "source", "context", "adminChoice"):
        if k not in out and k in other:
            out[k] = copy.deepcopy(other[k])
    return out


def merge_prog(mine, theirs, mine_n, theirs_n, deck_id, log):
    if mine is None:
        return copy.deepcopy(theirs)
    if theirs is None:
        return copy.deepcopy(mine)
    # deck-level fields: one side only -> kept; both -> the side with higher asked (tie: mine)
    winner = theirs if num(theirs.get("asked")) > num(mine.get("asked")) else mine
    out = {}
    for k in list(mine) + [k for k in theirs if k not in mine]:
        if k == "m":
            continue
        if k in mine and k in theirs:
            out[k] = copy.deepcopy(winner[k])
        else:
            out[k] = copy.deepcopy(mine[k] if k in mine else theirs[k])
    mm, tm = mine.get("m") or {}, theirs.get("m") or {}
    m = {}
    for cid in list(mm) + [c for c in tm if c not in mm]:
        if cid in mm and cid in tm:
            w, why = further_along(mm[cid], tm[cid], mine_n > theirs_n, theirs_n > mine_n)
            m[cid] = copy.deepcopy(tm[cid] if w == "b" else mm[cid])
            if w != "same":
                log.append(f"  {deck_id} {cid}: kept the {'later' if w == 'b' else 'earlier'} "
                           f"file's record ({why})")
        else:
            m[cid] = copy.deepcopy(mm.get(cid, tm.get(cid)))
    if "m" in mine or "m" in theirs:
        out["m"] = m
    return out


class Expected:
    """What the database should hold."""

    def __init__(self):
        self.folders, self.entries = [], []
        self.decks, self.prog = {}, {}
        self.copies = {}           # deck id -> [(file name, deck)]
        self.prog_copies = {}      # deck id -> [(file name, prog or None)]
        self.prefs, self.exams = None, {}
        self.skipped = []
        self.merge_log = []


def build_expected(files) -> Expected:
    ex = Expected()
    for f in files:                          # oldest 'exported' first
        data, name = f["data"], f["name"]
        lib = data.get("library") or {}
        for fo in lib.get("folders") or []:
            if not any(x.get("id") == fo.get("id") for x in ex.folders):
                ex.folders.append(copy.deepcopy(fo))
        for meta in lib.get("decks") or []:
            did = meta.get("id")
            deck = (data.get("decks") or {}).get(did)
            if not isinstance(deck, dict) or not isinstance(deck.get("concepts"), list):
                ex.skipped.append(f"{name}: {did} ({meta.get('name')}) has no content")
                continue
            prog = (data.get("prog") or {}).get(did)
            ex.copies.setdefault(did, []).append((name, deck))
            ex.prog_copies.setdefault(did, []).append((name, prog))
            existing = ex.decks.get(did)
            ex_n = len((existing or {}).get("concepts") or [])
            merged = merge_deck(existing, deck)
            ex.prog[did] = merge_prog(ex.prog.get(did), prog, ex_n,
                                      len(deck.get("concepts") or []), did, ex.merge_log)
            entry = next((e for e in ex.entries if e.get("id") == did), None)
            if entry is None:
                entry = copy.deepcopy(meta)
                if not any(x.get("id") == entry.get("folderId") for x in ex.folders):
                    if not any(x.get("name") == "Restored" for x in ex.folders):
                        ex.folders.append({"id": "f-restored", "name": "Restored"})
                    entry["folderId"] = next(x["id"] for x in ex.folders
                                             if x.get("name") == "Restored")
                ex.entries.append(entry)
            else:
                for k, v in meta.items():
                    if k not in entry:
                        entry[k] = copy.deepcopy(v)
                if existing is not None and not same(existing, merged):
                    entry["nCon"], entry["nQ"] = badge(merged)
            ex.decks[did] = merged
        for did, draft in (data.get("exams") or {}).items():
            ex.exams[did] = copy.deepcopy(draft)          # newer file wins
    v2 = [f for f in files if f["data"].get("v", 1) >= 2 and f["data"].get("prefs")]
    if v2:
        ex.prefs = copy.deepcopy(v2[-1]["data"]["prefs"])
    return ex


def apply_decisions(ex: Expected, decisions, out) -> list:
    """Apply Elisha's decisions to a copy of the expected state. Returns checks to run on the
    database later: [(kind, decision)]."""
    later = []
    for d in decisions:
        t = d.get("type")
        if t == "rename_deck":
            e = next(e for e in ex.entries if e["id"] == d["deck"])
            e["name"] = d["name"]
            ex.decks[d["deck"]]["name"] = d["name"]
        elif t == "add_folder":
            if not any(x.get("id") == d["folder"]["id"] for x in ex.folders):
                ex.folders.append(copy.deepcopy(d["folder"]))
        elif t == "move_deck":
            e = next(e for e in ex.entries if e["id"] == d["deck"])
            e["folderId"] = d["folder"]
        elif t == "carry_over_progress":
            carry_over(ex, d, out)
        elif t in ("assert_not_in_deck", "note"):
            pass
        else:
            out.append(f"  UNKNOWN decision type {t!r} (id {d.get('id')}): not checked")
        later.append(d)
    return later


def carry_over(ex: Expected, d, out):
    src, dst = ex.decks[d["from"]], ex.decks[d["to"]]
    sp = ex.prog.get(d["from"]) or {}
    if ex.prog.get(d["to"]) is None:
        ex.prog[d["to"]] = {"m": {}}
    dp = ex.prog[d["to"]]
    dp.setdefault("m", {})
    out.append(f"  carry_over_progress {d['from']} -> {d['to']} (fuller: {d['fuller']}), "
               f"further-along rule of DATA-MIGRATION.md, recomputed here:")
    for name in d["concept_names"]:
        a = [c for c in src.get("concepts") or [] if norm(c.get("name")) == norm(name)]
        b = [c for c in dst.get("concepts") or [] if norm(c.get("name")) == norm(name)]
        if len(a) != 1 or len(b) != 1:
            out.append(f"    {name}: MISMATCH not exactly one match ({len(a)} in from, "
                       f"{len(b)} in to)")
            continue
        srec = (sp.get("m") or {}).get(a[0]["id"])
        drec = dp["m"].get(b[0]["id"])
        if srec is None:
            w, why = "b", "only the 'to' deck has a record"
        elif drec is None:
            w, why = "a", "only the 'from' deck has a record"
        else:
            w, why = further_along(srec, drec, d["fuller"] == d["from"], d["fuller"] == d["to"])
        if w == "a":
            dp["m"][b[0]["id"]] = copy.deepcopy(srec)
        fmt = lambda r: ("none" if r is None else
                         f"box {r.get('box')} right {r.get('right')} due {r.get('due')}")
        out.append(f"    {name}: from {a[0]['id']} [{fmt(srec)}] vs to {b[0]['id']} "
                   f"[{fmt(drec)}] -> winner: "
                   f"{ {'a': 'from (copied over)', 'b': 'to (kept)', 'same': 'identical', 'undecided': 'UNDECIDED (to kept)'}[w]}"
                   f" ({why})")


# ---------------------------------------------------------------------------------------
# INVENTORY.md


def parse_inventory(path: Path):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8-sig")
    shas = {}
    for m in re.finditer(r"^## File: `([^`]+)`(.*?)(?=^## )", text, re.M | re.S):
        s = re.search(r"\|\s*SHA-256\s*\|\s*`([0-9a-f]{64})`", m.group(2))
        if s:
            shas[m.group(1)] = s.group(1)
    sec = re.search(r"^## Merged total.*?(?=^## )", text, re.M | re.S)
    rows, total = {}, None
    n = r"\**([\d,]+)\**"
    if sec:
        for line in sec.group(0).splitlines():
            m = re.match(r"^\|\s*(.+?)\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*" + r"\s*\|\s*".join(
                [n] * 4) + r"\s*\|\s*" + n + r"\s*\(" + n + r"\)\s*\|\s*" + n + r"\s*\|\s*$",
                line)
            if m:
                g = [int(x.replace(",", "")) for x in m.groups()[3:]]
                rows[m.group(2)] = dict(zip(("concepts", "questions", "cards", "guide", "courses",
                                             "problems", "records"), g))
            t = re.match(r"^\|\s*\*\*Total: (\d+) unique decks\*\*\s*\|[^|]*\|[^|]*\|\s*" +
                         r"\s*\|\s*".join([n] * 4) + r"\s*\|\s*\**([\d,]+) \(([\d,]+)\)\**\s*\|\s*"
                         + n + r"\s*\|", line)
            if t:
                g = [int(x.replace(",", "")) for x in t.groups()]
                total = dict(zip(("decks", "concepts", "questions", "cards", "guide", "courses",
                                  "problems", "records"), g))
    return shas, rows, total


# ---------------------------------------------------------------------------------------


class Result:
    def __init__(self):
        self.mismatches = 0
        self.lines = []

    def say(self, s=""):
        print(s)

    def bad(self, s):
        self.mismatches += 1
        print(s)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Verify the Drill import (read-only).")
    ap.add_argument("--data-dir", help="DATA_DIR (default: DATA_DIR env var, then .env)")
    ap.add_argument("--after-study", action="store_true",
                    help="Phase 7: allow more than the backups hold, require nothing lost")
    ap.add_argument("--no-inventory", action="store_true",
                    help="skip the INVENTORY.md cross-check (synthetic data only)")
    args = ap.parse_args(argv)
    exact = not args.after_study
    r = Result()

    dd = args.data_dir or read_env_data_dir()
    if not dd:
        print("CANNOT RUN: DATA_DIR not given and not in .env")
        return 2
    data_dir = Path(dd)
    db_path, import_dir = data_dir / "drill.db", data_dir / "import"
    dec_path = data_dir / "import-decisions.json"
    names = sorted(glob.glob(str(import_dir / "drill-backup-*.json")))
    if not db_path.is_file() or not names:
        print(f"CANNOT RUN: need {db_path} and {import_dir}\\drill-backup-*.json")
        return 2

    r.say(f"verify_import  mode: {'exact (fresh import)' if exact else 'after-study (Phase 7)'}")
    r.say(f"DATA_DIR  {data_dir}")
    r.say(f"database  {db_path} (opened read-only)")
    r.say("")

    # ---- backup files -------------------------------------------------------------------
    files = []
    for p in map(Path, names):
        with open(p, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8-sig")
        files.append({"name": p.name, "path": p, "raw": text, "sha": hashlib.sha256(raw).hexdigest(),
                      "size": len(raw), "data": json.loads(text)})
    files.sort(key=lambda f: (str(f["data"].get("exported") or ""), f["name"]))
    r.say(f"Backup files ({len(files)}), merged oldest 'exported' first:")
    for f in files:
        r.say(f"  {f['name']}  v{f['data'].get('v')}  exported {f['data'].get('exported')}  "
              f"{f['size']:,} bytes  sha256 {f['sha']}")

    inv_shas, inv_rows, inv_total = {}, {}, None
    inv_path = import_dir / "INVENTORY.md"
    if args.no_inventory:
        r.say("INVENTORY.md cross-check: skipped (--no-inventory)")
    elif not inv_path.is_file():
        r.bad(f"MISMATCH INVENTORY.md not found at {inv_path}")
    else:
        inv_shas, inv_rows, inv_total = parse_inventory(inv_path)
        if not inv_rows or not inv_total:
            r.bad("MISMATCH could not read the 'Merged total' table of INVENTORY.md")
        for f in files:
            want = inv_shas.get(f["name"])
            if want is None:
                r.bad(f"  MISMATCH {f['name']} is not in INVENTORY.md (regenerate it)")
            elif want != f["sha"]:
                r.bad(f"  MISMATCH {f['name']} sha256 {f['sha']} != INVENTORY.md {want} "
                      "(the file has CHANGED)")
            else:
                r.say(f"  {f['name']}  sha256 matches INVENTORY.md: ok")
        for n_ in inv_shas:
            if n_ not in {f["name"] for f in files}:
                r.bad(f"  MISMATCH INVENTORY.md lists {n_}, which is no longer in import\\")

    decisions = []
    if dec_path.is_file():
        with open(dec_path, "rb") as fh:
            decisions = json.loads(fh.read().decode("utf-8-sig")).get("decisions") or []
        r.say(f"Decisions file: {dec_path} ({len(decisions)} decisions)")
    else:
        r.say(f"Decisions file: none at {dec_path}")

    # ---- expected -----------------------------------------------------------------------
    pre = build_expected(files)
    post = copy.deepcopy(pre)
    dec_lines = []
    later = apply_decisions(post, decisions, dec_lines)
    for s in pre.skipped:
        r.say(f"  deck listed without content, not importable: {s}")

    # ---- database -----------------------------------------------------------------------
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    kv_text = dict(conn.execute("SELECT key, value FROM kv"))
    hist = conn.execute("SELECT key, value, replaced_at FROM kv_history ORDER BY rowid").fetchall()
    tables = {t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    imp_files = (dict(conn.execute("SELECT sha256, name FROM import_files"))
                 if "import_files" in tables else {})
    notes = (set(conn.execute("SELECT deck_id, note FROM import_notes"))
             if "import_notes" in tables else set())
    applied = ({x for (x,) in conn.execute("SELECT id FROM import_decisions_applied")}
               if "import_decisions_applied" in tables else set())
    conn.close()
    kv = {}
    for k, t in kv_text.items():
        try:
            kv[k] = json.loads(t)
        except ValueError:
            r.bad(f"MISMATCH kv[{k}] is not valid JSON")
    db_lib = kv.get("library") or {}
    db_entries = {e.get("id"): e for e in db_lib.get("decks") or []}
    db_folders = {f.get("id"): f.get("name") for f in db_lib.get("folders") or []}
    ex_folders = {f.get("id"): f.get("name") for f in post.folders}

    # ---- per-deck counts ------------------------------------------------------------------
    r.say("")
    r.say("Per deck: expected (from the backup files) / found (in drill.db). "
          "INV = expected equals INVENTORY.md's merged row.")
    cols = [("concepts", "concepts"), ("questions", "questions"), ("cards", "flashcards"),
            ("guide", "guide"), ("courses", "courses"), ("problems", "problems"),
            ("records", "progress")]
    hdr = f"{'deck id':<14}{'name':<26}" + "".join(f"{h:^13}" for _, h in cols)
    r.say(hdr + f"  {'folder (expected / found)':<60}INV  result")
    tot_e = dict.fromkeys([c for c, _ in cols], 0)
    tot_f = dict.fromkeys([c for c, _ in cols], 0)
    tot_inv_ok = True
    for e in post.entries:
        did = e["id"]
        ce = counts(post.decks.get(did), post.prog.get(did), e)
        cpre = counts(pre.decks.get(did), pre.prog.get(did), e)
        cf = counts(kv.get(f"deck:{did}"), kv.get(f"prog:{did}"), db_entries.get(did))
        cells, ok = [], True
        for c, _ in cols:
            tot_e[c] += ce[c]
            tot_f[c] += cf[c]
            good = cf[c] == ce[c] if exact else cf[c] >= ce[c]
            ok &= good
            cells.append(f"{ce[c]:>6}/{cf[c]:<5}{'' if good else '!':1}")
        fe = f"{ex_folders.get(ce['folder'], '?')} ({ce['folder']})"
        ff = f"{db_folders.get(cf['folder'], '?')} ({cf['folder']})"
        fok = ce["folder"] == cf["folder"]
        folder = fe if fok else f"{fe} / {ff}"
        if not fok and exact:
            ok = False
        if f"deck:{did}" not in kv:
            ok = False
        inv = "-"
        if inv_rows:
            row = inv_rows.get(did)
            inv_ok = row is not None and all(row[c] == cpre[c] for c, _ in cols)
            tot_inv_ok &= inv_ok
            inv = "ok" if inv_ok else "BAD"
            ok &= inv_ok
        line = (f"{did:<14}{str(e.get('name'))[:25]:<26}" + "".join(cells) +
                f"  {folder[:59]:<60}{inv:<5}{'ok' if ok else 'MISMATCH'}")
        (r.say if ok else r.bad)(line)
    line = (f"{'TOTAL':<14}{str(len(post.entries)) + ' decks / ' + str(len(db_entries)):<26}" +
            "".join(f"{tot_e[c]:>6}/{tot_f[c]:<6}" for c, _ in cols))
    tot_ok = all((tot_e[c] == tot_f[c]) if exact else (tot_f[c] >= tot_e[c]) for c, _ in cols)
    tot_ok &= (len(post.entries) == len(db_entries)) if exact else (
        len(db_entries) >= len(post.entries))
    (r.say if tot_ok else r.bad)(line + ("  ok" if tot_ok else "  MISMATCH"))
    if inv_total:
        inv_line = (f"{'INVENTORY.md':<14}{str(inv_total['decks']) + ' decks':<26}" +
                    "".join(f"{inv_total[c]:>6}{'':7}" for c, _ in cols))
        same_inv = (inv_total["decks"] == len(pre.entries) and
                    all(inv_total[c] == sum(counts(pre.decks.get(e['id']), pre.prog.get(e['id']),
                                                   e)[c] for e in pre.entries) for c, _ in cols)
                    and tot_inv_ok and set(inv_rows) == {e["id"] for e in pre.entries})
        (r.say if same_inv else r.bad)(inv_line + ("  ok (= expected)" if same_inv
                                                   else "  MISMATCH with expected"))
    for did in db_entries:
        if did not in {e["id"] for e in post.entries}:
            (r.bad if exact else r.say)(f"{'MISMATCH' if exact else 'info'} library has deck "
                                        f"{did} ({db_entries[did].get('name')}) that no backup has")

    # ---- duplicates -----------------------------------------------------------------------
    r.say("")
    multi = {d: c for d, c in pre.copies.items() if len(c) > 1}
    r.say(f"Same deck id in more than one file: {len(multi)}")
    for d, c in multi.items():
        r.say(f"  {d}: " + "; ".join(f"{fn} {len(dk.get('concepts') or [])} concepts"
                                     for fn, dk in c))
    for s in pre.merge_log:
        r.say(f"  further-along choice (recomputed):{s[1:]}")
    by_name = {}
    for e in pre.entries:
        by_name.setdefault(e.get("name"), []).append(e["id"])
    dup = {n_: ids for n_, ids in by_name.items() if len(ids) > 1}
    r.say(f"Different ids, same deck name (all kept, flagged): {len(dup)} name(s)")
    for n_, ids in dup.items():
        present = [i for i in ids if f"deck:{i}" in kv_text]
        (r.say if len(present) == len(ids) else r.bad)(
            f"  {n_!r}: {len(ids)} decks {ids}, {len(present)} in the database"
            f"{'' if len(present) == len(ids) else ' MISMATCH'}")

    # ---- decisions ----------------------------------------------------------------------
    r.say("")
    r.say("Decisions (expected changes, recomputed independently):")
    for s in dec_lines:
        (r.bad if "MISMATCH" in s else r.say)(s)
    for d in later:
        t, i = d.get("type"), d.get("id")
        if t in ("rename_deck", "add_folder", "move_deck", "carry_over_progress"):
            (r.say if i in applied else r.bad)(
                f"  {i}: {'recorded' if i in applied else 'MISMATCH NOT recorded'} "
                "in import_decisions_applied")
        elif t == "note":
            k = (d["deck"], d["note"])
            (r.say if k in notes else r.bad)(
                f"  {i}: note {d['deck']} '{d['note']}' "
                f"{'in import_notes' if k in notes else 'MISMATCH missing from import_notes'}")
        elif t == "assert_not_in_deck":
            db_names = {norm(c.get("name")) for c in
                        (kv.get(f"deck:{d['deck']}") or {}).get("concepts") or []}
            hit = [n_ for n_ in d["concept_names"] if norm(n_) in db_names]
            (r.bad if hit else r.say)(f"  {i}: {d['concept_names']} in {d['deck']}: "
                                      f"{'MISMATCH present: ' + str(hit) if hit else 'none, ok'}")

    # ---- content: deck, prog, library, prefs, exams ----------------------------------------
    r.say("")
    r.say("Content (deep comparison of the stored JSON with the backup files):")
    single = {did: len(c) == 1 for did, c in post.copies.items()}
    raw_all = [f["raw"] for f in files]

    def verbatim(prefix, text):
        return any((prefix + text) in raw for raw in raw_all)

    def compare(key, pre_v, post_v, found, order, byte_prefix=None):
        if found is None and key not in kv:
            r.bad(f"  {key}: MISMATCH missing from database")
            return
        d_post = diff(post_v, found, order=order)
        changed = not same(pre_v, post_v, order=True)
        if exact and d_post:
            r.bad(f"  {key}: MISMATCH {len(d_post)} difference(s) from the backup:")
            for s in d_post:
                r.say(f"      {s}")
            return
        if not exact and d_post:
            r.say(f"  {key}: info, {len(d_post)} change(s) since the backup "
                  f"(first: {d_post[0]})")
            return
        msg = ("identical to the backup" if byte_prefix is not None
               else "identical to the merge of the copies, recomputed here")
        if changed:
            dd_ = diff(pre_v, found, order=order)
            msg = f"identical except the documented decision change(s): " + "; ".join(dd_)
        if byte_prefix is not None and not changed:
            if verbatim(byte_prefix, kv_text[key]):
                msg += ", byte-identical"
            elif order:
                r.bad(f"  {key}: MISMATCH equal as JSON but its text is not verbatim in the file")
                return
        r.say(f"  {key}: {msg}")

    for e in post.entries:
        did = e["id"]
        one = single.get(did, True)
        compare(f"deck:{did}", pre.decks.get(did), post.decks.get(did), kv.get(f"deck:{did}"),
                one, f'"{did}":' if one else None)
        # every concept / card of every copy is present (by id, else by name for concepts)
        dbd = kv.get(f"deck:{did}") or {}
        by_id = {c.get("id"): c for c in dbd.get("concepts") or []}
        by_name = {norm(c.get("name")) for c in dbd.get("concepts") or []}
        cards = {k.get("id"): k for k in dbd.get("cards") or []}
        for fname, cp in post.copies.get(did, []):
            n_id = n_name = miss = qs_short = n_var = 0
            for c in cp.get("concepts") or []:
                if c.get("id") in by_id:
                    n_id += 1
                    if not same(c, by_id[c["id"]]):
                        n_var += 1
                    if len(by_id[c["id"]].get("qs") or []) < len(c.get("qs") or []):
                        qs_short += 1
                elif norm(c.get("name")) in by_name:
                    n_name += 1
                else:
                    miss += 1
            kmiss = sum(1 for k in cp.get("cards") or [] if k.get("id") not in cards)
            if not one or miss or kmiss or qs_short:
                line = (f"    copy in {fname}: {len(cp.get('concepts') or [])} concepts -> "
                        f"{n_id} present by id ({n_var} of them stored in the other copy's "
                        f"version), {n_name} by name (stored under the other copy's id), "
                        f"{miss} MISSING; "
                        f"{len(cp.get('cards') or [])} flashcards -> {kmiss} MISSING; "
                        f"concepts with fewer questions: {qs_short}")
                (r.bad if miss or kmiss or qs_short else r.say)(line)
                if n_var or n_name:
                    r.say(f"      note: {n_var + n_name} concept(s) of this copy are stored in "
                          "the other copy's version (merge rule: fuller copy is the base); "
                          f"this copy's text for them is only in {fname}")
        pv = post.prog.get(did)
        prog_null = all(p is None for _, p in post.prog_copies.get(did, []))
        if prog_null:
            if f"prog:{did}" in kv_text and kv.get(f"prog:{did}") is not None:
                (r.bad if exact else r.say)(
                    f"  prog:{did}: {'MISMATCH' if exact else 'info'} file has prog = null "
                    f"but the database holds a record ({counts(None, kv[f'prog:{did}'], None)['records']} records)")
            elif f"prog:{did}" in kv_text:
                r.say(f"  prog:{did}: file prog = null, database holds null: ok")
            else:
                r.say(f"  prog:{did}: file prog = null (Drill had no prog key), database has "
                      "no key; the app reads null either way: ok")
        else:
            compare(f"prog:{did}", pre.prog.get(did), pv, kv.get(f"prog:{did}"),
                    one, f'"{did}":' if one else None)
            if not exact:
                m = (kv.get(f"prog:{did}") or {}).get("m") or {}
                lost = [c for c in (pv or {}).get("m") or {} if c not in m]
                if lost:
                    r.bad(f"    MISMATCH {len(lost)} progress record(s) gone: {lost[:5]}")

    lib_pre = {"folders": pre.folders, "decks": pre.entries}
    lib_post = {"folders": post.folders, "decks": post.entries}
    one_file = len(files) == 1
    if one_file:
        lib_pre = copy.deepcopy(files[0]["data"]["library"])
    compare("library", lib_pre, lib_post, kv.get("library"), one_file,
            '"library":' if one_file else None)
    r.say(f"    folders expected: {[f.get('name') for f in post.folders]}")
    r.say(f"    folders found:    {[f.get('name') for f in db_lib.get('folders') or []]}")
    for e in post.entries:
        de = db_entries.get(e["id"])
        if de:
            deck = kv.get(f"deck:{e['id']}") or {}
            if (de.get("nCon"), de.get("nQ")) != badge(deck):
                r.say(f"    note: {e['id']} badge nCon/nQ {de.get('nCon')}/{de.get('nQ')} vs "
                      f"content {badge(deck)[0]}/{badge(deck)[1]}")

    if post.prefs is None:
        r.say(f"  prefs: no v2 file has prefs; database {'has' if 'prefs' in kv else 'has no'} "
              "prefs (see kv keys below)")
    else:
        compare("prefs", post.prefs, post.prefs, kv.get("prefs"), True, '"prefs":')
    db_exams = sorted(k for k in kv if k.startswith("exam:"))
    want_exams = sorted(f"exam:{k}" for k in post.exams)
    if db_exams == want_exams and not want_exams:
        r.say("  exams: the files have none; database has no exam:* keys: ok")
    for did in post.exams:
        compare(f"exam:{did}", post.exams[did], post.exams[did], kv.get(f"exam:{did}"), False,
                f'"{did}":')
    for k in db_exams:
        if k[5:] not in post.exams:
            (r.bad if exact else r.say)(f"  {k}: {'MISMATCH' if exact else 'info'} not in any file")

    # ---- keys ---------------------------------------------------------------------------
    r.say("")
    want = {"library"} | {f"deck:{e['id']}" for e in post.entries}
    want |= {f"prog:{d}" for d, p in post.prog.items() if p is not None}
    want |= {f"exam:{d}" for d in post.exams}
    if post.prefs is not None:
        want.add("prefs")
    extra = sorted(set(kv_text) - want)
    missing = sorted(want - set(kv_text))
    r.say(f"kv keys: expected {len(want)}, found {len(kv_text)}")
    (r.bad if missing else r.say)(f"  missing: {missing if missing else 'none'}")
    (r.bad if (extra and exact) else r.say)(f"  extra:   {extra if extra else 'none'}")

    # ---- kv_history ---------------------------------------------------------------------
    r.say("")
    changed_keys = []
    if one_file:
        pre_vals = {"library": files[0]["data"]["library"],
                    **{f"deck:{d}": v for d, v in pre.decks.items()},
                    **{f"prog:{d}": v for d, v in pre.prog.items()}}
    else:
        pre_vals = {"library": lib_pre, **{f"deck:{d}": v for d, v in pre.decks.items()},
                    **{f"prog:{d}": v for d, v in pre.prog.items()}}
    post_vals = {"library": lib_post, **{f"deck:{d}": v for d, v in post.decks.items()},
                 **{f"prog:{d}": v for d, v in post.prog.items()}}
    for k in pre_vals:
        if not same(pre_vals[k], post_vals.get(k), order=True):
            changed_keys.append(k)
    r.say(f"kv_history: {len(hist)} row(s); keys a decision changed: {changed_keys or 'none'}")
    used = set()
    for k in changed_keys:
        rows = [(i, h) for i, h in enumerate(hist) if h[0] == k]
        if not rows:
            r.bad(f"  {k}: MISMATCH no kv_history row holds its pre-decision value")
            continue
        i, (_, text, at) = rows[0]
        used.add(i)
        try:
            val = json.loads(text)
        except ValueError:
            val = object()
        d_ = diff(pre_vals[k], val, order=True)
        prefix = '"library":' if k == "library" else f'"{k.split(":", 1)[1]}":'
        vb = one_file and verbatim(prefix, text)
        if d_:
            r.bad(f"  {k}: MISMATCH first history row ({at}) differs from the file: {d_[:3]}")
        else:
            r.say(f"  {k}: first history row ({at}) = the file's value"
                  f"{', byte-identical' if vb else ''}: ok")
    for i, (k, text, at) in enumerate(hist):
        if i not in used:
            (r.bad if exact else r.say)(f"  {'MISMATCH' if exact else 'info'} unexplained "
                                        f"history row: {k} replaced {at}")

    # ---- import_files and file hashes ---------------------------------------------------------
    r.say("")
    for f in files:
        (r.say if f["sha"] in imp_files else r.bad)(
            f"import_files: {f['name']} {'recorded' if f['sha'] in imp_files else 'MISMATCH NOT recorded'}")
        after = sha256_file(f["path"])
        (r.say if after == f["sha"] else r.bad)(
            f"sha256 now: {f['name']} {after} {'unchanged' if after == f['sha'] else 'CHANGED'}")

    r.say("")
    if r.mismatches:
        r.say(f"RESULT: FAIL, {r.mismatches} mismatch(es)")
        return 1
    r.say("RESULT: PASS, every check matched")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"CANNOT RUN: {e}")
        sys.exit(2)
