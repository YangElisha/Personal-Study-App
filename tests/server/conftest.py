"""Every server test runs against a scratch DATA_DIR in a temp folder, never the real one."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from server.settings import REPO_ROOT, Settings, read_env_file  # noqa: E402

REAL_DATA_DIR = read_env_file(REPO_ROOT / ".env").get("DATA_DIR", "")


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """No test may reach the real Ollama or the real `claude`: by default the AI router sees a
    closed port for Ollama and CLAUDE_CLI=off. tests/server/test_ai.py sets its own fakes."""
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CLAUDE_CLI", "off")
    monkeypatch.setenv("CLAUDE_CLI_PATH", "drill-no-such-claude-program")
    monkeypatch.setenv("CLAUDE_REACH_HOST", "127.0.0.1:9")
    # Phase 9: the CLIs under test see sign-in off unless a test turns it on, whatever the
    # real .env says; never the real Google client values.
    monkeypatch.setenv("AUTH_MODE", "off")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret-not-real")


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "DrillData"
    (d / "import").mkdir(parents=True)
    # anything that calls load_settings() (the CLIs) sees the scratch folder
    monkeypatch.setenv("DATA_DIR", str(d))
    monkeypatch.setenv("BACKUP_KEEP", "5")
    assert not REAL_DATA_DIR or not str(d.resolve()).lower().startswith(
        str(Path(REAL_DATA_DIR).resolve()).lower())
    return d


@pytest.fixture
def settings(data_dir) -> Settings:
    return Settings(data_dir=data_dir.resolve(), backup_keep=5, port=8765)


@pytest.fixture
def make_client(settings, tmp_path):
    from fastapi.testclient import TestClient
    from server.app import create_app

    def make(app_dir=None, client_ip="127.0.0.1", base_url="http://127.0.0.1:8765",
             app_settings=None, **kw):
        # MODULES.md goes to the scratch folder, never the repo's copy
        kw.setdefault("modules_md_paths", [tmp_path / "repo-MODULES.md",
                                           settings.data_dir / "MODULES.md"])
        kw.setdefault("detect_tailscale", False)     # never run the real tailscale CLI
        app = create_app(app_settings or settings, app_dir=app_dir or (tmp_path / "no-app"), **kw)
        # the client address is simulated: the server only answers loopback when phone
        # access is off, and Tailscale (or LAN) addresses only when it is on
        return TestClient(app, base_url=base_url, client=(client_ip, 50000),
                          follow_redirects=False)
    return make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def history(settings, key=None):
    conn = sqlite3.connect(settings.db_path)
    try:
        if key is None:
            return conn.execute("SELECT key, value FROM kv_history ORDER BY rowid").fetchall()
        return [r[0] for r in conn.execute(
            "SELECT value FROM kv_history WHERE key=? ORDER BY rowid", (key,))]
    finally:
        conn.close()


def kv(settings) -> dict:
    conn = sqlite3.connect(settings.db_path)
    try:
        return dict(conn.execute("SELECT key, value FROM kv").fetchall())
    finally:
        conn.close()


def kv_full(settings) -> list:
    conn = sqlite3.connect(settings.db_path)
    try:
        return conn.execute("SELECT key, value, updated_at FROM kv ORDER BY key").fetchall()
    finally:
        conn.close()
