"""Database snapshots in DATA_DIR\\backups, made with SQLite's online backup API.

Regular snapshots (on start, daily) are named  drill-YYYYMMDD-HHMMSS.db  (a -N suffix is
added if two land in the same second). Only files matching exactly that pattern are ever
pruned, newest BACKUP_KEEP kept.

Safety snapshots taken before an import or a restore are named
drill-YYYYMMDD-HHMMSS-pre-import.db / -pre-restore.db. They do not match the pattern, so
pruning never touches them.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import db

REGULAR = re.compile(r"^drill-(\d{8}-\d{6})(?:-(\d+))?\.db$")


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _free_name(backups_dir: Path, stamp: str, tag: str) -> Path:
    base = f"drill-{stamp}" + (f"-{tag}" if tag else "")
    p = backups_dir / f"{base}.db"
    n = 1
    while p.exists():
        n += 1
        p = backups_dir / (f"drill-{stamp}-{n}" + (f"-{tag}" if tag else "") + ".db")
    return p


def backup_to(src_db: Path, dest: Path) -> None:
    """Copy src_db into dest (a new file) with the backup API, then make dest standalone."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    src = db.connect(src_db)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")   # one self-contained file, no -wal
            ok = dst.execute("PRAGMA quick_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"snapshot failed its integrity check: {ok}")
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(tmp, dest)   # the final name only ever points to a complete snapshot


def take_snapshot(settings, tag: str = "", now: datetime | None = None) -> Path | None:
    """Snapshot drill.db. Returns the file, or None if there is no database yet."""
    if not settings.db_path.exists():
        return None
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    dest = _free_name(settings.backups_dir, _stamp(now), tag)
    backup_to(settings.db_path, dest)
    if not tag:
        prune(settings)
    return dest


def regular_snapshots(backups_dir: Path) -> list[Path]:
    """Regular snapshots, oldest first."""
    if not backups_dir.is_dir():
        return []
    found = []
    for p in backups_dir.iterdir():
        m = REGULAR.match(p.name)
        if m and p.is_file():
            found.append(((m.group(1), int(m.group(2) or 1)), p))
    return [p for _, p in sorted(found)]


def prune(settings) -> list[Path]:
    snaps = regular_snapshots(settings.backups_dir)
    extra = snaps[:-settings.backup_keep] if len(snaps) > settings.backup_keep else []
    for p in extra:
        p.unlink()
    return extra


def newest_regular_time(backups_dir: Path) -> datetime | None:
    snaps = regular_snapshots(backups_dir)
    if not snaps:
        return None
    return datetime.strptime(REGULAR.match(snaps[-1].name).group(1), "%Y%m%d-%H%M%S")


def daily_due(settings, now: datetime | None = None) -> bool:
    last = newest_regular_time(settings.backups_dir)
    now = now or datetime.now()
    return last is None or (now - last).total_seconds() >= 24 * 3600
