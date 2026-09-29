"""Desktop launcher (MonoSpace.exe): settings paths, first-run file, port choice, finding a
running server. The window itself is checked on the built exe (see packaging/build.ps1)."""
from __future__ import annotations

import json
import socket

from server import launcher, settings as st


def test_monospace_home_moves_settings_and_local_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MONOSPACE_HOME", str(tmp_path))
    assert st.desktop_settings_file() == tmp_path.resolve() / "settings.env"
    assert st.desktop_local_dir() == tmp_path.resolve() / "local"
    assert launcher.default_data_dir() == tmp_path.resolve() / "MonoSpaceData"


def test_default_paths_without_override(monkeypatch):
    monkeypatch.delenv("MONOSPACE_HOME", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\A")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\L")
    monkeypatch.setenv("USERPROFILE", r"C:\U")
    assert str(st.desktop_settings_file()) == r"C:\A\MonoSpace\settings.env"
    assert str(st.desktop_local_dir()) == r"C:\L\MonoSpace"
    assert str(launcher.default_data_dir()) == r"C:\U\MonoSpaceData"


def test_settings_template_loads(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    f = tmp_path / "settings.env"
    f.write_text(launcher.SETTINGS_TEMPLATE.format(data_dir=d), encoding="utf-8")
    s = st.load_settings(env_file=f, environ={})
    assert s.data_dir == d.resolve() and s.port == 8765 and s.backup_keep == 30


def test_first_run_writes_settings_but_never_overwrites(tmp_path):
    f = tmp_path / "sub" / "settings.env"
    d = tmp_path / "data"
    d.mkdir()
    assert launcher.write_settings_file(f, d) is True
    assert st.load_settings(env_file=f, environ={}).data_dir == d.resolve()
    f.write_text("DATA_DIR=C:\\keep\\me\n", encoding="utf-8")
    assert launcher.write_settings_file(f, tmp_path / "other") is False
    assert f.read_text(encoding="utf-8") == "DATA_DIR=C:\\keep\\me\n"


def test_pick_port_skips_a_busy_port():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        p, note = launcher.pick_port(port)
        assert p > port and "another program" in note and f"port {p}" in note
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert launcher.pick_port(free) == (free, None)


def test_find_running_needs_same_data_dir_and_a_live_server(tmp_path, settings):
    local = tmp_path / "local"
    local.mkdir()
    # no note, nothing listening on settings.port in the test -> None (8765 may be a real
    # server on a developer PC, so use a closed port)
    import dataclasses
    s = dataclasses.replace(settings, port=9)
    assert launcher.find_running(s, local) is None
    (local / "running.json").write_text(json.dumps(
        {"port": 9, "data_dir": str(tmp_path / "other")}), encoding="utf-8")
    assert launcher.find_running(s, local) is None
