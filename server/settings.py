"""Settings, read from the repo's .env.

A process environment variable with the same name overrides the .env value (the tests
use this to point DATA_DIR at a scratch folder). Nothing else is read.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

DEFAULTS = {"BACKUP_KEEP": "30", "PORT": "8765", "PHONE_ACCESS": "off",
            "PHONE_ALLOW_LAN": "off", "PHONE_HOSTS": "", "AUTH_MODE": "off",
            "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}
ENV_KEYS = ("DATA_DIR", "BACKUP_KEEP", "PORT", "PHONE_ACCESS", "PHONE_ALLOW_LAN", "PHONE_HOSTS",
            "AUTH_MODE", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
AUTH_MODES = ("off", "google")


class SettingsError(Exception):
    """The server must not start with these settings."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    backup_keep: int
    port: int
    # Phase 8 (server/phone.py): phone access over Tailscale, off by default
    phone_access: bool = False
    phone_allow_lan: bool = False
    phone_hosts: tuple = ()
    # Phase 9 (server/accounts.py, server/google_auth.py): Google sign-in, off by default.
    # The secret is never printed: repr=False keeps it out of any repr/log of Settings.
    auth_mode: str = "off"
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    # Whose data this is. None = DATA_DIR itself (Elisha's existing drill.db, modules and
    # backups; also everything when AUTH_MODE=off). Otherwise DATA_DIR/users/<id>.
    user_dir: Path | None = None

    def for_user(self, user_dir: Path | None) -> "Settings":
        """The same settings, with drill.db / backups / modules / import in user_dir."""
        return replace(self, user_dir=user_dir)

    @property
    def root(self) -> Path:
        """The folder holding this user's drill.db, backups, modules and import folders."""
        return self.user_dir if self.user_dir is not None else self.data_dir

    @property
    def is_main_data(self) -> bool:
        return self.user_dir is None

    @property
    def accounts_db(self) -> Path:
        """Allow-list, sessions and sign-in events (Phase 9). Separate from every drill.db,
        so a snapshot restore can never bring back a revoked session."""
        return self.data_dir / "accounts.db"

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"

    @property
    def phone_db(self) -> Path:
        """PIN hash and phone sessions. Separate from drill.db so a snapshot restore can
        never bring back an old PIN or revoked sessions."""
        return self.data_dir / "phone-access.db"

    @property
    def db_path(self) -> Path:
        return self.root / "drill.db"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def import_dir(self) -> Path:
        return self.root / "import"

    @property
    def decisions_file(self) -> Path:
        return self.root / "import-decisions.json"

    @property
    def lock_file(self) -> Path:
        # one lock for the whole DATA_DIR, whichever user's data a process works on
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
    for k in ENV_KEYS:
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
    flags = {}
    for k in ("PHONE_ACCESS", "PHONE_ALLOW_LAN"):
        v = values[k].strip().lower()
        if v in ("on", "1", "true", "yes"):
            flags[k] = True
        elif v in ("off", "0", "false", "no", ""):
            flags[k] = False
        else:
            raise SettingsError(f"{k} must be on or off, got {values[k]!r}.")
    hosts = tuple(h.strip().lower().rstrip(".") for h in values["PHONE_HOSTS"].replace(";", ",")
                  .split(",") if h.strip())
    mode = values["AUTH_MODE"].strip().lower() or "off"
    if mode not in AUTH_MODES:
        raise SettingsError(f"AUTH_MODE must be off or google, got {values['AUTH_MODE']!r}.")
    cid = values["GOOGLE_CLIENT_ID"].strip()
    secret = values["GOOGLE_CLIENT_SECRET"].strip()
    if mode == "google":
        missing = [k for k, v in (("GOOGLE_CLIENT_ID", cid), ("GOOGLE_CLIENT_SECRET", secret))
                   if not v]
        if missing:
            raise SettingsError(
                f"AUTH_MODE=google needs {' and '.join(missing)} in .env (from the Google "
                "Cloud Console; see docs/API.md, Sign-in). Or set AUTH_MODE=off.")
    return Settings(data_dir=data_dir, backup_keep=keep, port=port,
                    phone_access=flags["PHONE_ACCESS"], phone_allow_lan=flags["PHONE_ALLOW_LAN"],
                    phone_hosts=hosts, auth_mode=mode, google_client_id=cid,
                    google_client_secret=secret)
