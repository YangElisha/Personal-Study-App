"""Restore drill.db from a snapshot:  python -m server.restore [<snapshot file or name>]
                                        [--user <email>]

--user: another account's own database (Phase 9). Default: DATA_DIR itself, as before.

Without an argument it lists the snapshots in DATA_DIR\\backups.
- Refuses to run while the server (or an import) is running.
- Shows what will be replaced, and asks you to type  yes.
- First snapshots the current database as drill-<ts>-pre-restore.db, so a restore never
  loses anything: restoring that file undoes the restore.
- Copies the snapshot into drill.db with SQLite's backup API (no file copy of an open db).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from . import db, snapshots
from .instance_lock import AlreadyRunning, InstanceLock
from .settings import SettingsError, load_settings


def summarize(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = dict(conn.execute("SELECT key, value FROM kv").fetchall())
        last = conn.execute("SELECT MAX(updated_at) FROM kv").fetchone()[0]
        hist = conn.execute("SELECT COUNT(*) FROM kv_history").fetchone()[0]
    finally:
        conn.close()
    lib = json.loads(rows.get("library", "null")) or {"decks": []}
    decks = {}
    for e in lib.get("decks") or []:
        d = json.loads(rows.get(f"deck:{e.get('id')}", "null")) or {}
        p = json.loads(rows.get(f"prog:{e.get('id')}", "null")) or {}
        decks[e.get("id")] = (e.get("name"), len(d.get("concepts") or []),
                              len(p.get("m") or {}))
    return {"keys": rows, "last": last, "history": hist, "decks": decks}


def describe(cur: dict, snap: dict) -> list[str]:
    out = [f"  {'':<22}{'now (will be replaced)':>24}{'snapshot (will be restored)':>30}",
           f"  {'keys':<22}{len(cur['keys']):>24}{len(snap['keys']):>30}",
           f"  {'decks':<22}{len(cur['decks']):>24}{len(snap['decks']):>30}",
           f"  {'last change':<22}{str(cur['last']):>24}{str(snap['last']):>30}",
           f"  {'history rows':<22}{cur['history']:>24}{snap['history']:>30}"]
    ck, sk = cur["keys"], snap["keys"]
    differ = sorted(k for k in set(ck) | set(sk) if ck.get(k) != sk.get(k))
    out.append(f"  keys that differ: {len(differ)}")
    for k in differ[:40]:
        state = ("only now" if k not in sk else "only in snapshot" if k not in ck else "different")
        out.append(f"    {k}  ({state})")
    if len(differ) > 40:
        out.append(f"    ... and {len(differ) - 40} more")
    for did in sorted(set(cur["decks"]) | set(snap["decks"])):
        a, b = cur["decks"].get(did), snap["decks"].get(did)
        if a != b:
            out.append(f"    deck {did}: now {a}  ->  snapshot {b}   (name, concepts, progress)")
    return out


def resolve_snapshot(settings, arg: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        p = settings.backups_dir / arg
    if not p.is_file():
        raise FileNotFoundError(f"No snapshot at {p}")
    return p


def restore(settings, snapshot: Path, ask=None, say=None) -> bool:
    """Returns True if restored. Caller must hold the instance lock."""
    ask = ask or input
    say = say or print
    if snapshot.resolve() == settings.db_path.resolve():
        raise ValueError("That is the live database, not a snapshot.")
    snap = summarize(snapshot)
    if settings.db_path.exists():
        cur = summarize(settings.db_path)
    else:
        cur = {"keys": {}, "last": None, "history": 0, "decks": {}}
    say(f"Restore {snapshot.name} into {settings.db_path}")
    for line in describe(cur, snap):
        say(line)
    answer = ask("Type yes to replace the current database with this snapshot: ")
    if answer.strip() != "yes":
        say("Not restored. Nothing changed.")
        return False
    if settings.db_path.exists():
        pre = snapshots.take_snapshot(settings, tag="pre-restore")
        say(f"Current database saved first as {pre}")
    src = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
    try:
        dst = db.connect(settings.db_path)
        try:
            with db.WRITE_LOCK:
                src.backup(dst)
            dst.execute("PRAGMA journal_mode=WAL")
            ok = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    db.checkpoint(settings.db_path)
    after = summarize(settings.db_path)
    same = after["keys"] == snap["keys"]
    say(f"Restored. integrity: {ok}; database now matches the snapshot: {'yes' if same else 'NO'}")
    return same and ok == "ok"


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import argparse
    from .accounts import AccountError, settings_for_email
    ap = argparse.ArgumentParser(prog="python -m server.restore")
    ap.add_argument("snapshot", nargs="?")
    ap.add_argument("--user", metavar="EMAIL")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    argv = [args.snapshot] if args.snapshot else []
    try:
        settings = settings_for_email(load_settings(), args.user)
    except (SettingsError, AccountError) as e:
        print(f"Not restored: {e}")
        return 2
    if not argv:
        print(f"Snapshots in {settings.backups_dir}:")
        for p in sorted(settings.backups_dir.glob("drill-*.db")):
            print(f"  {p.name}  {p.stat().st_size:,} bytes")
        print("Restore one with:  python -m server.restore <name>")
        return 0
    try:
        snapshot = resolve_snapshot(settings, argv[0])
        with InstanceLock(settings.lock_file, "restore"):
            return 0 if restore(settings, snapshot) else 1
    except AlreadyRunning as e:
        print(f"Not restored: {e}")
        return 2
    except (FileNotFoundError, ValueError, sqlite3.Error) as e:
        print(f"Not restored: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
