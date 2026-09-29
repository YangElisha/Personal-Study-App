"""Module library (Phase 6): uploaded PDFs, their fingerprints, their decks, MODULES.md.

- A PDF is identified by its SHA-256. Uploading a known one changes nothing but a
  `reupload` event ("no changes").
- New PDFs are stored in DATA_DIR\\modules\\. An existing file is never overwritten: a
  different file with the same name gets `-<sha8>` before `.pdf`; an identical one is reused.
- When the app has built (and saved) the deck, it reports the deck id. The server reads the
  deck from `kv`, records its terms (name, topic, content hash) and diffs them against the
  previous version of the same module (same file name, else same deck name).
- Every write adds a row to `module_events`; nothing is deleted. A deck report that replaces
  an earlier one keeps the earlier values in its event row.
- MODULES.md is regenerated after every write, in the repo root and in DATA_DIR.

CLI:  python -m server.modules register <pdf> --deck <deck id> [--name <file name>]
      python -m server.modules list
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import uuid
from pathlib import Path

from . import db
from .settings import REPO_ROOT, Settings

MAX_UPLOAD = 400 * 1024 * 1024          # Module 3 is 115 MB
CHUNK = 1024 * 1024
FILE_LOCK = threading.RLock()            # file placement in DATA_DIR\modules, one at a time


class ModuleError(Exception):
    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


# ---- helpers ----------------------------------------------------------------------------

def norm(s) -> str:
    """Port of the app's `const norm = s => (s||"").toLowerCase().replace(/[^a-z0-9]/g,"")`."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _clean(v):
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    return v


def term_hash(concept: dict) -> str:
    """Content of a term = fact, items, steps (whitespace runs collapsed). Not the name
    (that is the match key), not topic or pages (moving a term is not changing it)."""
    body = {k: _clean(concept.get(k)) for k in ("fact", "items", "steps")}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def safe_file_name(name: str) -> str:
    base = re.split(r"[\\/]", str(name or ""))[-1].strip()
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip(" .")
    if not base:
        base = "module"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[:180]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def count_pdf_pages(path: Path) -> int | None:
    """Best effort (no PDF library): counts `/Type /Page` objects. Only used when the deck
    has no coverage report. Misses pages hidden in compressed object streams."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    n = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
    return n or None


def modules_dir(settings: Settings) -> Path:
    d = settings.root / "modules"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _row(conn, sha) -> dict | None:
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM modules WHERE sha256=?", (sha,)).fetchone()
    finally:
        conn.row_factory = None
    return dict(r) if r else None


def _event(conn, sha, event, detail) -> None:
    conn.execute("INSERT INTO module_events(sha256, event, detail, at) VALUES(?,?,?,?)",
                 (sha, event, json.dumps(detail, ensure_ascii=False), db.now_iso()))


def _deck_exists(conn, deck_id) -> bool:
    return bool(deck_id) and conn.execute(
        "SELECT 1 FROM kv WHERE key=?", ("deck:" + deck_id,)).fetchone() is not None


def _previous(conn, sha: str, file_name: str, deck_name: str | None = None) -> dict | None:
    """The newest other version (with a deck recorded) of the same module: same file name
    (case-insensitive), else same deck name (norm)."""
    me = _row(conn, sha)
    before = me["uploaded_at"] if me else "9999"
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM modules WHERE sha256<>? AND deck_id IS NOT NULL AND uploaded_at<=? "
            "ORDER BY uploaded_at DESC", (sha, before))]
    finally:
        conn.row_factory = None
    for r in rows:
        if r["file_name"].lower() == file_name.lower():
            return r
    if deck_name:
        for r in rows:
            if norm(r["deck_name"]) == norm(deck_name):
                return r
    return None


def _prev_summary(p: dict | None) -> dict | None:
    if not p:
        return None
    return {"sha256": p["sha256"], "file_name": p["file_name"], "deck_id": p["deck_id"],
            "deck_name": p["deck_name"], "uploaded_at": p["uploaded_at"],
            "terms": [t["name"] for t in json.loads(p["terms_json"] or "[]")]}


def diff_terms(old: list[dict], new: list[dict]) -> dict:
    o = {}
    for t in old:
        o.setdefault(norm(t["name"]), t)
    n = {}
    for t in new:
        n.setdefault(norm(t["name"]), t)
    added = [t["name"] for k, t in n.items() if k not in o]
    removed = [t["name"] for k, t in o.items() if k not in n]
    changed = [t["name"] for k, t in n.items() if k in o and o[k]["hash"] != t["hash"]]
    unchanged = sum(1 for k, t in n.items() if k in o and o[k]["hash"] == t["hash"])
    return {"added": added, "changed": changed, "removed": removed, "unchanged": unchanged}


# ---- upload -----------------------------------------------------------------------------

def _place(settings: Settings, tmp: Path, sha: str, file_name: str) -> str:
    """Move the finished temp file into DATA_DIR\\modules. Never overwrites a different file.
    Returns the stored name."""
    d = modules_dir(settings)
    stem = file_name[:-4]
    candidates = [file_name, f"{stem}-{sha[:8]}.pdf"] + [f"{stem}-{sha[:8]}-{i}.pdf"
                                                          for i in range(2, 100)]
    with FILE_LOCK:
        for name in candidates:
            target = d / name
            if target.exists():
                if target.is_file() and sha256_file(target) == sha:
                    tmp.unlink()                    # identical file already there: reuse it
                    return name
                continue
            os.replace(tmp, target)                 # target does not exist: nothing replaced
            return name
    raise ModuleError(409, "name_clash", f"No free file name for {file_name}")


def new_temp(settings: Settings) -> Path:
    return modules_dir(settings) / f".incoming-{uuid.uuid4().hex}.part"


def finish_upload(settings: Settings, tmp: Path, sha: str, size: int, file_name: str,
                  md_paths) -> dict:
    """Called with the complete upload in `tmp` (already hashed)."""
    file_name = safe_file_name(file_name)
    conn = db.connect(settings.db_path)
    try:
        row = _row(conn, sha)
        if row and row["stored_name"] and (modules_dir(settings) / row["stored_name"]).is_file():
            tmp.unlink(missing_ok=True)
            with db.transaction(conn):
                _event(conn, sha, "reupload", {"file_name": file_name, "size": size})
            write_modules_md(settings, md_paths)
            if row["deck_id"]:
                return {"ok": True, "known": True, "sha256": sha, "file_name": row["file_name"],
                        "stored_name": row["stored_name"], "deck_id": row["deck_id"],
                        "deck_name": row["deck_name"], "deck_exists": _deck_exists(conn, row["deck_id"]),
                        "pages": row["pages"], "terms": row["term_count"],
                        "uploaded_at": row["uploaded_at"]}
            # stored before, but no deck was ever reported (build interrupted): build again
            return {"ok": True, "known": False, "sha256": sha, "file_name": row["file_name"],
                    "stored_name": row["stored_name"], "size": size, "resumed": True,
                    "previous": _prev_summary(_previous(conn, sha, row["file_name"]))}
        stored = _place(settings, tmp, sha, file_name)
        ts = db.now_iso()
        with db.transaction(conn):
            if row:     # row exists but its file went missing: point it at the new copy
                conn.execute("UPDATE modules SET stored_name=? WHERE sha256=?", (stored, sha))
                _event(conn, sha, "file_restored", {"old_stored_name": row["stored_name"],
                                                     "stored_name": stored})
            else:
                conn.execute(
                    "INSERT INTO modules(sha256, file_name, stored_name, size, uploaded_at) "
                    "VALUES(?,?,?,?,?)", (sha, file_name, stored, size, ts))
                _event(conn, sha, "upload", {"file_name": file_name, "stored_name": stored,
                                             "size": size})
        write_modules_md(settings, md_paths)
        return {"ok": True, "known": False, "sha256": sha, "file_name": file_name,
                "stored_name": stored, "size": size, "resumed": False,
                "previous": _prev_summary(_previous(conn, sha, file_name))}
    finally:
        conn.close()


# ---- deck report ------------------------------------------------------------------------

def _deck_info(conn, deck_id: str) -> tuple[str, list[dict], dict | None]:
    got = db.get(conn, "deck:" + deck_id)
    if got is None:
        raise ModuleError(404, "deck_not_found", f"No deck stored under deck:{deck_id}")
    try:
        deck = json.loads(got[0])
    except ValueError:
        raise ModuleError(409, "bad_deck", f"deck:{deck_id} is not valid JSON") from None
    if not isinstance(deck, dict):
        raise ModuleError(409, "bad_deck", f"deck:{deck_id} is not a deck object")
    name = deck.get("name") or ""
    lib = db.get(conn, "library")
    if lib:
        try:
            for e in (json.loads(lib[0]) or {}).get("decks") or []:
                if isinstance(e, dict) and e.get("id") == deck_id and e.get("name"):
                    name = e["name"]
        except (ValueError, AttributeError):
            pass
    terms = [{"name": str(c.get("name") or ""), "topic": c.get("topic"),
              "pages": c.get("pages"), "hash": term_hash(c)}
             for c in deck.get("concepts") or [] if isinstance(c, dict)]
    cov = deck.get("coverage") if isinstance(deck.get("coverage"), dict) else None
    return name, terms, cov


def record_deck(settings: Settings, sha: str, deck_id: str, md_paths,
                pages: int | None = None, previous_sha: str | None = None,
                event: str = "deck") -> dict:
    conn = db.connect(settings.db_path)
    try:
        row = _row(conn, sha)
        if row is None:
            raise ModuleError(404, "module_not_found", f"No module with sha256 {sha}")
        deck_name, terms, cov = _deck_info(conn, deck_id)
        if cov and isinstance(cov.get("pages"), int) and cov["pages"] > 0:
            pages = cov["pages"]
        if not pages and row["stored_name"]:
            pages = count_pdf_pages(modules_dir(settings) / row["stored_name"])
        cov_small = None
        if cov:
            cov_small = {k: cov.get(k) for k in ("pages", "content", "dividers", "cover",
                                                  "skipped", "empty", "notext", "terms")}
        if previous_sha:
            prev = _row(conn, previous_sha)
            if prev is None or not prev["deck_id"]:
                raise ModuleError(404, "previous_not_found",
                                  f"No module with a deck under sha256 {previous_sha}")
        else:
            prev = _previous(conn, sha, row["file_name"], deck_name)
        diff = (diff_terms(json.loads(prev["terms_json"] or "[]"), terms) if prev else None)
        new = {"deck_id": deck_id, "deck_name": deck_name, "pages": pages,
               "term_count": len(terms),
               "terms_json": json.dumps(terms, ensure_ascii=False),
               "coverage_json": json.dumps(cov_small, ensure_ascii=False) if cov_small else None,
               "previous_sha": prev["sha256"] if prev else None,
               "diff_json": json.dumps(diff, ensure_ascii=False) if diff else None}
        same = all(row.get(k) == v for k, v in new.items())
        if not same:
            with db.transaction(conn):
                old = {k: row.get(k) for k in new} if row["deck_id"] else None
                conn.execute(
                    "UPDATE modules SET deck_id=?, deck_name=?, pages=?, term_count=?, "
                    "terms_json=?, coverage_json=?, previous_sha=?, diff_json=?, "
                    "deck_recorded_at=? WHERE sha256=?",
                    (*new.values(), db.now_iso(), sha))
                _event(conn, sha, event, {"deck_id": deck_id, "replaced": old})
            write_modules_md(settings, md_paths)
        out = {"ok": True, "sha256": sha, "deck_id": deck_id, "deck_name": deck_name,
               "pages": pages, "terms": len(terms), "status": "unchanged" if same else "recorded",
               "previous": _prev_summary(prev), "first_upload": prev is None}
        out.update(diff or {"added": [t["name"] for t in terms], "changed": [], "removed": [],
                            "unchanged": 0})
        return out
    finally:
        conn.close()


# ---- listing and MODULES.md --------------------------------------------------------------

def list_modules(settings: Settings) -> list[dict]:
    conn = db.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM modules ORDER BY uploaded_at DESC")]
        last = {r["sha256"]: r["at"] for r in conn.execute(
            "SELECT sha256, MAX(at) AS at FROM module_events WHERE event='reupload' GROUP BY sha256")}
        conn.row_factory = None
        out = []
        for r in rows:
            out.append({"sha256": r["sha256"], "file_name": r["file_name"],
                        "stored_name": r["stored_name"], "size": r["size"], "pages": r["pages"],
                        "uploaded_at": r["uploaded_at"], "deck_id": r["deck_id"],
                        "deck_name": r["deck_name"], "deck_exists": _deck_exists(conn, r["deck_id"]),
                        "terms": r["term_count"], "previous_sha": r["previous_sha"],
                        "changes": json.loads(r["diff_json"]) if r["diff_json"] else None,
                        "coverage": json.loads(r["coverage_json"]) if r["coverage_json"] else None,
                        "last_reupload_at": last.get(r["sha256"])})
        return out
    finally:
        conn.close()


def _md_esc(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def _names(xs: list[str]) -> str:
    return ", ".join(_md_esc(x) for x in xs) if xs else "none"


def render_modules_md(mods: list[dict]) -> str:
    L = ["# MODULES", "",
         "Generated by the Drill server (`server/modules.py`) after every module upload. "
         "Do not edit by hand.",
         "Every module PDF uploaded to Drill, newest first: its deck, term count, fingerprint "
         "(SHA-256), and what changed since the previous upload of the same module. Dates are UTC.",
         ""]
    if not mods:
        L += ["_No modules uploaded yet._", ""]
        return "\n".join(L)
    L += ["| Module | Deck | Terms | Pages | Uploaded | SHA-256 | Changes |",
          "|---|---|---|---|---|---|---|"]
    for m in mods:
        if not m["deck_id"]:
            ch = "deck not built yet"
        elif m["changes"] is None:
            ch = "first upload"
        else:
            c = m["changes"]
            if not (c["added"] or c["changed"] or c["removed"]):
                ch = "no changes to terms"
            else:
                ch = f"+{len(c['added'])} added, {len(c['changed'])} changed, -{len(c['removed'])} removed"
        L.append(f"| {_md_esc(m['file_name'])} | {_md_esc(m['deck_name'] or '-')} | "
                 f"{m['terms'] if m['terms'] is not None else '-'} | "
                 f"{m['pages'] if m['pages'] is not None else '-'} | {m['uploaded_at'][:10]} | "
                 f"`{m['sha256'][:12]}` | {ch} |")
    L.append("")
    for m in mods:
        L += [f"## {_md_esc(m['file_name'])} ({m['uploaded_at'][:10]})", ""]
        L.append(f"- Deck: {_md_esc(m['deck_name']) if m['deck_id'] else 'not built yet'}"
                 + (f" (`{m['deck_id']}`)" if m["deck_id"] else "")
                 + ("" if not m["deck_id"] or m["deck_exists"] else " (deck no longer in the library)"))
        L.append(f"- Terms: {m['terms'] if m['terms'] is not None else '-'}; "
                 f"pages: {m['pages'] if m['pages'] is not None else '-'}; "
                 f"size: {m['size'] / 1048576:.1f} MB")
        L.append(f"- Uploaded: {m['uploaded_at'][:16].replace('T', ' ')} UTC; "
                 f"stored as `modules/{_md_esc(m['stored_name'])}`")
        L.append(f"- SHA-256: `{m['sha256']}`")
        cov = m.get("coverage")
        if cov:
            L.append(f"- Coverage: {cov.get('content')} content slides, "
                     f"{len(cov.get('empty') or [])} with text but no term, "
                     f"{len(cov.get('skipped') or [])} skipped")
        if m["last_reupload_at"]:
            L.append(f"- Uploaded again {m['last_reupload_at'][:16].replace('T', ' ')} UTC: "
                     "identical file, no changes")
        if m["deck_id"]:
            c = m["changes"]
            if c is None:
                L.append("- Changes: first upload of this module")
            else:
                L.append(f"- Changes since the previous upload (`{(m['previous_sha'] or '')[:12]}`): "
                         f"{c['unchanged']} terms unchanged")
                L.append(f"  - Added ({len(c['added'])}): {_names(c['added'])}")
                L.append(f"  - Changed ({len(c['changed'])}): {_names(c['changed'])}")
                L.append(f"  - Removed ({len(c['removed'])}): {_names(c['removed'])}")
        L.append("")
    return "\n".join(L)


def default_md_paths(settings: Settings) -> list[Path]:
    """Elisha's data (DATA_DIR itself): the repo's MODULES.md and DATA_DIR's copy. Any other
    account (Phase 9): only its own folder's copy; the repo's index stays Elisha's."""
    if settings.is_main_data:
        return [REPO_ROOT / "MODULES.md", settings.data_dir / "MODULES.md"]
    return [settings.root / "MODULES.md"]


def write_modules_md(settings: Settings, md_paths=None) -> None:
    text = render_modules_md(list_modules(settings))
    for p in (default_md_paths(settings) if md_paths is None else md_paths):
        p = Path(p)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, p)


# ---- CLI --------------------------------------------------------------------------------

def register(settings: Settings, pdf: Path, deck_id: str, file_name: str | None = None,
             md_paths=None, previous_sha: str | None = None) -> dict:
    """Record an existing PDF against an existing deck (backfill). A PDF already inside
    DATA_DIR\\modules is used where it is; one elsewhere is copied in (never overwriting)."""
    pdf = Path(pdf).resolve()
    if not pdf.is_file():
        raise ModuleError(404, "file_not_found", f"{pdf} does not exist")
    db.init_db(settings.db_path)
    sha = sha256_file(pdf)
    size = pdf.stat().st_size
    d = modules_dir(settings).resolve()
    name = safe_file_name(file_name or pdf.name)
    conn = db.connect(settings.db_path)
    try:
        _deck_info(conn, deck_id)           # 404 before anything is written
        row = _row(conn, sha)
        if row and row["deck_id"] and row["deck_id"] != deck_id:
            raise ModuleError(409, "already_registered",
                              f"{pdf.name} is already registered with deck {row['deck_id']} "
                              f"({row['deck_name']}); nothing changed")
        if row is None:
            if pdf.parent == d:
                stored = pdf.name
            else:
                tmp = new_temp(settings)
                shutil.copyfile(pdf, tmp)
                stored = _place(settings, tmp, sha, name)
            with db.transaction(conn):
                conn.execute(
                    "INSERT INTO modules(sha256, file_name, stored_name, size, uploaded_at) "
                    "VALUES(?,?,?,?,?)", (sha, name, stored, size, db.now_iso()))
                _event(conn, sha, "register", {"source": str(pdf), "stored_name": stored,
                                               "size": size})
    finally:
        conn.close()
    return record_deck(settings, sha, deck_id, md_paths, previous_sha=previous_sha,
                       event="register_deck")


def main(argv=None) -> int:
    from .instance_lock import AlreadyRunning, InstanceLock
    from .settings import SettingsError, load_settings
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m server.modules")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--user", metavar="EMAIL",
                        help="another account's library (Phase 9); default: DATA_DIR itself")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", parents=[common],
                       help="record an existing PDF against an existing deck")
    r.add_argument("pdf")
    r.add_argument("--deck", required=True, help="deck id (the part after deck:)")
    r.add_argument("--name", help="file name to record (default: the PDF's own name)")
    r.add_argument("--previous", help="sha256 of the earlier version to diff against")
    sub.add_parser("list", parents=[common], help="list recorded modules")
    args = ap.parse_args(argv)
    from .accounts import AccountError, settings_for_email
    try:
        settings = settings_for_email(load_settings(), args.user)
    except (SettingsError, AccountError) as e:
        print(f"Stopped: {e}")
        return 2
    try:
        with InstanceLock(settings.lock_file, "modules"):
            db.init_db(settings.db_path)
            if args.cmd == "list":
                for m in list_modules(settings):
                    print(f"{m['sha256'][:12]}  {m['file_name']}  deck={m['deck_id']} "
                          f"({m['deck_name']})  terms={m['terms']}  pages={m['pages']}")
                return 0
            out = register(settings, Path(args.pdf), args.deck, args.name,
                           previous_sha=args.previous)
    except AlreadyRunning as e:
        print(f"Not registered: {e}")
        return 2
    except ModuleError as e:
        print(f"Not registered: {e.message}")
        return 1
    print(f"Registered {out['sha256'][:12]} -> deck {out['deck_id']} ({out['deck_name']}): "
          f"{out['terms']} terms, {out['pages']} pages, {out['status']}")
    if out["first_upload"]:
        print("First upload of this module.")
    else:
        print(f"vs {out['previous']['sha256'][:12]}: added {out['added']}, changed "
              f"{out['changed']}, removed {out['removed']}, unchanged {out['unchanged']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
