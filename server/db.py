"""SQLite store: the kv table the app reads and writes, plus kv_history.

Rules enforced here, for every writer (API, importer, decisions):
- every overwrite and every delete first copies the old value into kv_history;
- writing a value identical to the stored one is a no-op (no history row, updated_at kept);
- one transaction per write (BEGIN IMMEDIATE ... COMMIT).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv_history (
  key TEXT, value TEXT, replaced_at TEXT
);
CREATE INDEX IF NOT EXISTS kv_history_key ON kv_history(key);
-- backup files that have been imported (by content hash); a re-run inserts nothing
CREATE TABLE IF NOT EXISTS import_files (
  sha256 TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
  exported TEXT, first_imported_at TEXT NOT NULL
);
-- notes from Elisha's import decisions that are not app data ("rename later", ...)
CREATE TABLE IF NOT EXISTS import_notes (
  deck_id TEXT NOT NULL, note TEXT NOT NULL, source TEXT, created_at TEXT NOT NULL,
  UNIQUE(deck_id, note)
);
-- one-off import decisions already applied; each is applied at most once
CREATE TABLE IF NOT EXISTS import_decisions_applied (
  id TEXT PRIMARY KEY, detail TEXT, applied_at TEXT NOT NULL
);
"""

# One writer at a time inside this process (the API runs handlers on a thread pool).
WRITE_LOCK = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10, isolation_level=None,
                           check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create the database (if missing) and the tables (if missing). Never drops anything."""
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    with WRITE_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    # keep drill.db itself current, so OneDrive's copy of the main file is up to date
    try:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        pass


# ---- operations that must run inside transaction() -------------------------------------

def put_in_tx(conn: sqlite3.Connection, key: str, text: str, ts: str | None = None) -> str:
    """Write one value. Returns 'added', 'changed' or 'unchanged'."""
    ts = ts or now_iso()
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO kv(key, value, updated_at) VALUES(?,?,?)", (key, text, ts))
        return "added"
    if row[0] == text:
        return "unchanged"
    conn.execute("INSERT INTO kv_history(key, value, replaced_at) VALUES(?,?,?)",
                 (key, row[0], ts))
    conn.execute("UPDATE kv SET value=?, updated_at=? WHERE key=?", (text, ts, key))
    return "changed"


def delete_in_tx(conn: sqlite3.Connection, key: str, ts: str | None = None) -> bool:
    """Delete one key, keeping its value in kv_history. Returns False if it did not exist."""
    ts = ts or now_iso()
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return False
    conn.execute("INSERT INTO kv_history(key, value, replaced_at) VALUES(?,?,?)",
                 (key, row[0], ts))
    conn.execute("DELETE FROM kv WHERE key=?", (key,))
    return True


# ---- convenience wrappers ---------------------------------------------------------------

def get(conn: sqlite3.Connection, key: str) -> tuple[str, str] | None:
    row = conn.execute("SELECT value, updated_at FROM kv WHERE key=?", (key,)).fetchone()
    return (row[0], row[1]) if row else None


def put(conn: sqlite3.Connection, key: str, text: str) -> tuple[str, str]:
    with transaction(conn):
        status = put_in_tx(conn, key, text)
        ts = conn.execute("SELECT updated_at FROM kv WHERE key=?", (key,)).fetchone()[0]
    return status, ts


def delete(conn: sqlite3.Connection, key: str) -> bool:
    with transaction(conn):
        return delete_in_tx(conn, key)


def list_keys(conn: sqlite3.Connection, prefix: str = "") -> list[str]:
    if not prefix:
        rows = conn.execute("SELECT key FROM kv ORDER BY key").fetchall()
    else:
        rows = conn.execute("SELECT key FROM kv WHERE substr(key, 1, ?) = ? ORDER BY key",
                            (len(prefix), prefix)).fetchall()
    return [r[0] for r in rows]


def checkpoint(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
