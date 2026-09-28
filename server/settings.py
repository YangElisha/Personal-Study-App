"""Settings, read from the repo's .env.

A process environment variable with the same name overrides the .env value (the tests
use this to point DATA_DIR at a scratch folder). Nothing else is read.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

DEFAULTS = {"BACKUP_KEEP": "30", "PORT": "8765"}


class SettingsError(Exception):
    """The server must not start with these settings."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    backup_keep: int
    port: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "drill.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def import_dir(self) -> Path:
        return self.data_dir / "import"

    @property
    def decisions_file(self) -> Path:
        return self.data_dir / "import-decisions.json"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "drill-server.lock"


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, # comments, optional surrounding quotes."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def _is_inside(child: Path, parent: Path) -> bool:
    c = os.path.normcase(str(child))
    p = os.path.normcase(str(parent))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def load_settings(env_file: Path | None = None, environ: dict | None = None,
                  repo_root: Path | None = None) -> Settings:
    env_file = ENV_FILE if env_file is None else env_file
    environ = os.environ if environ is None else environ
    repo_root = REPO_ROOT if repo_root is None else repo_root

    values = dict(DEFAULTS)
    values.update(read_env_file(env_file))
    for k in ("DATA_DIR", "BACKUP_KEEP", "PORT"):
        if environ.get(k):
            values[k] = environ[k]

    raw_dir = values.get("DATA_DIR", "").strip()
    if not raw_dir:
        raise SettingsError(f"DATA_DIR is not set (expected in {env_file}).")
    data_dir = Path(os.path.expandvars(os.path.expanduser(raw_dir)))
    if not data_dir.is_absolute():
        raise SettingsError(f"DATA_DIR must be an absolute path, got {raw_dir!r}.")
    data_dir = data_dir.resolve()
    if _is_inside(data_dir, repo_root.resolve()):
        raise SettingsError(
            f"DATA_DIR ({data_dir}) is inside the repo folder ({repo_root}). Personal data "
            "must never be stored in the repo. Point DATA_DIR in .env somewhere outside it.")
    if not data_dir.is_dir():
        # Refuse rather than create: a typo in .env would otherwise open an empty app.
        raise SettingsError(f"DATA_DIR ({data_dir}) does not exist. Create it or fix .env.")

    try:
        keep = int(values["BACKUP_KEEP"])
        port = int(values["PORT"])
    except ValueError as e:
        raise SettingsError(f"BACKUP_KEEP and PORT must be whole numbers ({e}).") from None
    if keep < 1:
        raise SettingsError("BACKUP_KEEP must be at least 1.")
    return Settings(data_dir=data_dir, backup_keep=keep, port=port)
