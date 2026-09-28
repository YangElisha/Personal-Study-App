"""Snapshots on start / daily, pruning to BACKUP_KEEP, and the restore CLI."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import pytest
from conftest import kv
from server import restore as restore_mod
from server import snapshots
from server.instance_lock import AlreadyRunning, InstanceLock


def regular(settings):
    return snapshots.regular_snapshots(settings.backups_dir)


def test_snapshot_on_every_start(make_client, settings):
    with make_client() as c:
        c.put("/api/store/deck%3A1", content=b'{"a":1}')
    first = regular(settings)
    assert len(first) == 1
    time.sleep(1.1)                       # a new second, so a new name
    with make_client():
        pass
    snaps = regular(settings)
    assert len(snaps) == 2
    # the second one holds the data written during the first run, as a standalone file
    conn = sqlite3.connect(snaps[-1])
    try:
        assert conn.execute("SELECT value FROM kv WHERE key='deck:1'").fetchone()[0] == '{"a":1}'
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert not list(settings.backups_dir.glob("*.tmp"))


def test_same_second_snapshots_get_distinct_names(make_client, settings):
    with make_client():
        pass
    now = datetime.now()
    a = snapshots.take_snapshot(settings, now=now)
    b = snapshots.take_snapshot(settings, now=now)
    assert a != b and a.exists() and b.exists()


def test_pruning_keeps_newest_and_only_touches_exact_pattern(make_client, settings):
    with make_client():
        pass
    bdir = settings.backups_dir
    base = datetime(2026, 1, 1, 8, 0, 0)
    for i in range(8):
        (bdir / f"drill-{(base + timedelta(days=i)).strftime('%Y%m%d-%H%M%S')}.db").write_bytes(b"x")
    keepers = ["drill-20200101-000000-pre-restore.db", "drill-20200101-000000-pre-import.db",
               "drill-latest.db", "notes.txt", "drill-2020.db", "Drill-20200101-000000.db.bak",
               "drill-20200101-000000.DB.old"]
    for k in keepers:
        (bdir / k).write_bytes(b"keep")
    new = snapshots.take_snapshot(settings)
    snaps = regular(settings)
    assert len(snaps) == settings.backup_keep == 5
    assert snaps[-1] == new
    for k in keepers:
        assert (bdir / k).exists(), k


def test_daily_due():
    class S:
        backups_dir = None
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        S.backups_dir = Path(t)
        assert snapshots.daily_due(S) is True
        (Path(t) / "drill-20260928-080000.db").write_bytes(b"x")
        assert snapshots.daily_due(S, now=datetime(2026, 9, 29, 7, 59, 59)) is False
        assert snapshots.daily_due(S, now=datetime(2026, 9, 29, 8, 0, 0)) is True


def test_daily_snapshot_loop_runs_while_server_is_up(make_client, settings, monkeypatch):
    monkeypatch.setattr(snapshots, "daily_due", lambda s, now=None: True)
    with make_client(daily_check_seconds=0.05):
        deadline = time.time() + 5
        while len(list(settings.backups_dir.glob("drill-*.db"))) < 2 and time.time() < deadline:
            time.sleep(0.05)
    assert len(list(settings.backups_dir.glob("drill-*.db"))) >= 2


# ---- restore ----------------------------------------------------------------------------

def _setup_with_snapshot(make_client, settings):
    with make_client() as c:
        c.put("/api/store/" + quote("deck:1"), content=b'{"v":"original"}')
    time.sleep(1.1)
    with make_client() as c:                      # this start snapshots the "original" state
        c.put("/api/store/" + quote("deck:1"), content=b'{"v":"changed"}')
        c.put("/api/store/" + quote("deck:new"), content=b"1")
    snap = regular(settings)[-1]
    return snap


def test_restore_declined_changes_nothing(make_client, settings):
    snap = _setup_with_snapshot(make_client, settings)
    before = kv(settings)
    out = []
    assert restore_mod.restore(settings, snap, ask=lambda _: "no", say=out.append) is False
    assert kv(settings) == before
    assert "Not restored" in out[-1]
    assert not list(settings.backups_dir.glob("*pre-restore*"))


def test_restore_yes_reverts_and_keeps_pre_restore_snapshot(make_client, settings):
    snap = _setup_with_snapshot(make_client, settings)
    out = []
    assert restore_mod.restore(settings, snap, ask=lambda _: "yes", say=out.append) is True
    now = kv(settings)
    assert now["deck:1"] == '{"v":"original"}' and "deck:new" not in now
    pre = list(settings.backups_dir.glob("drill-*-pre-restore.db"))
    assert len(pre) == 1
    conn = sqlite3.connect(pre[0])
    try:
        assert conn.execute("SELECT value FROM kv WHERE key='deck:1'").fetchone()[0] == '{"v":"changed"}'
    finally:
        conn.close()
    text = "\n".join(out)
    assert "deck:new  (only now)" in text and "deck:1  (different)" in text
    # the server still works on the restored database
    with make_client() as c:
        assert c.get("/api/store/deck%3A1").text == '{"v":"original"}'


def test_restore_only_exact_yes(make_client, settings):
    snap = _setup_with_snapshot(make_client, settings)
    for answer in ["y", "YES", "Yes", "", "yes please"]:
        assert restore_mod.restore(settings, snap, ask=lambda _: answer, say=lambda s: None) is False
    assert kv(settings)["deck:1"] == '{"v":"changed"}'


def test_restore_cli_refuses_while_server_running(make_client, settings, capsys, monkeypatch):
    snap = _setup_with_snapshot(make_client, settings)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("must not ask"))
    with InstanceLock(settings.lock_file, "server"):
        assert restore_mod.main([snap.name]) == 2
    assert "Not restored" in capsys.readouterr().out
    assert kv(settings)["deck:1"] == '{"v":"changed"}'


def test_restore_cli_with_typed_yes(make_client, settings, capsys, monkeypatch):
    snap = _setup_with_snapshot(make_client, settings)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert restore_mod.main([snap.name]) == 0
    assert kv(settings)["deck:1"] == '{"v":"original"}'
    assert list(settings.backups_dir.glob("drill-*-pre-restore.db"))


def test_restore_cli_lists_snapshots(make_client, settings, capsys):
    _setup_with_snapshot(make_client, settings)
    assert restore_mod.main([]) == 0
    assert "drill-" in capsys.readouterr().out


def test_instance_lock_is_exclusive(settings):
    with InstanceLock(settings.lock_file, "a"):
        with pytest.raises(AlreadyRunning):
            InstanceLock(settings.lock_file, "b").acquire()
    with InstanceLock(settings.lock_file, "c"):      # released -> free again
        pass
