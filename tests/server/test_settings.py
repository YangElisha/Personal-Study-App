"""Settings come from .env; env vars override; DATA_DIR inside the repo is refused."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from server.settings import REPO_ROOT, SettingsError, load_settings


def write_env(tmp_path, text):
    p = tmp_path / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_reads_env_file(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    env = write_env(tmp_path, f"# comment\nDATA_DIR={d}\nBACKUP_KEEP=7\nPORT=9999\nOTHER=x\n")
    s = load_settings(env_file=env, environ={})
    assert s.data_dir == d.resolve() and s.backup_keep == 7 and s.port == 9999
    assert s.db_path == d.resolve() / "drill.db"


def test_defaults_and_quotes(tmp_path):
    d = tmp_path / "da ta"
    d.mkdir()
    env = write_env(tmp_path, f'DATA_DIR="{d}"\n')
    s = load_settings(env_file=env, environ={})
    assert s.data_dir == d.resolve() and s.backup_keep == 30 and s.port == 8765


def test_environment_overrides_env_file(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    env = write_env(tmp_path, f"DATA_DIR={a}\nPORT=1\n")
    s = load_settings(env_file=env, environ={"DATA_DIR": str(b), "PORT": "2"})
    assert s.data_dir == b.resolve() and s.port == 2


@pytest.mark.parametrize("inside", ["", "data", "tests/server", "."])
def test_refuses_data_dir_inside_repo(tmp_path, inside):
    target = (REPO_ROOT / inside) if inside else REPO_ROOT
    env = write_env(tmp_path, f"DATA_DIR={target}\n")
    with pytest.raises(SettingsError, match="inside the repo"):
        load_settings(env_file=env, environ={})


def test_refuses_inside_repo_case_insensitive_on_windows(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows paths only")
    env = write_env(tmp_path, f"DATA_DIR={str(REPO_ROOT).upper()}\\SUB\n")
    with pytest.raises(SettingsError, match="inside the repo"):
        load_settings(env_file=env, environ={})


def test_refuses_missing_relative_or_unset(tmp_path):
    with pytest.raises(SettingsError, match="does not exist"):
        load_settings(env_file=write_env(tmp_path, f"DATA_DIR={tmp_path / 'nope'}\n"), environ={})
    with pytest.raises(SettingsError, match="absolute"):
        load_settings(env_file=write_env(tmp_path, "DATA_DIR=relative\\dir\n"), environ={})
    with pytest.raises(SettingsError, match="not set"):
        load_settings(env_file=write_env(tmp_path, "PORT=1\n"), environ={})
    d = tmp_path / "ok"
    d.mkdir()
    with pytest.raises(SettingsError, match="BACKUP_KEEP"):
        load_settings(env_file=write_env(tmp_path, f"DATA_DIR={d}\nBACKUP_KEEP=0\n"), environ={})


def test_server_process_refuses_to_start_with_data_dir_in_repo(tmp_path):
    env = dict(os.environ, DATA_DIR=str(REPO_ROOT / "data"), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "server"], cwd=REPO_ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT started" in r.stdout and "inside the repo" in r.stdout
    assert not (REPO_ROOT / "data").exists()
