"""In-app update (MonoSpace 2026-10-01).

Every build carries build-info.json (written by packaging\\build.ps1): its build id, when it was
built, the commit, and where new builds appear (the repo's dist\\ folder on this PC). Each build
also leaves dist\\MonoSpace-Setup.json beside MonoSpace-Setup.exe with the same fields plus the
installer's sha256.

check()   -> is there a newer build in that folder than the one running?
install() -> copy the installer out of dist\\ (so a rebuild can't change it mid-install), take a
             "pre-update" snapshot of the database, start a hidden helper that waits for this
             process to exit and then runs the installer silently with /RELAUNCH=1, and close
             the window (QUIT_HOOK, set by the launcher). The installer replaces the program
             files only ({app}); the data folder, settings and logs are never touched. It then
             starts the new MonoSpace.

Running from source (no build-info.json) there is nothing to update: that is what git is for.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import snapshots
from .settings import BUNDLE_ROOT

log = logging.getLogger("monospace.update")

INFO_NAME = "build-info.json"
SETUP_NAME = "MonoSpace-Setup.exe"
SETUP_INFO = "MonoSpace-Setup.json"
QUIT_HOOK = None        # set by the launcher: closes the window so the program files can be replaced


class UpdateError(Exception):
    pass


def _read_json(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))      # PowerShell may write a BOM
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def current_build(root: Path = BUNDLE_ROOT) -> dict | None:
    return _read_json(root / INFO_NAME)


def update_dir(cur: dict | None) -> Path | None:
    d = os.environ.get("MONOSPACE_UPDATE_DIR") or (cur or {}).get("update_dir")
    return Path(d) if d else None


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _public(info: dict | None) -> dict | None:
    return {k: info.get(k) for k in ("version", "build", "built_at", "commit")} if info else None


def check(root: Path = BUNDLE_ROOT) -> dict:
    """{"current", "available", "reason"}: reason is "source" (running from source), "no_source"
    (no build folder found), "up_to_date" or "" when a newer build is available."""
    cur = current_build(root)
    out = {"current": _public(cur), "available": None, "reason": ""}
    if not cur:
        out["reason"] = "source"
        return out
    d = update_dir(cur)
    new = _read_json(d / SETUP_INFO) if d else None
    if not new or not (d / SETUP_NAME).is_file():
        out["reason"] = "no_source"
        return out
    if new.get("build") == cur.get("build") or str(new.get("built_at", "")) <= str(cur.get("built_at", "")):
        out["reason"] = "up_to_date"
        return out
    out["available"] = _public(new)
    return out


def helper_command(pid: int, setup: Path, log_file: Path) -> list[str]:
    """A hidden PowerShell that waits for MonoSpace (pid) to exit, then installs silently."""
    q = lambda p: "'" + str(p).replace("'", "''") + "'"
    script = (f"Wait-Process -Id {pid} -Timeout 120 -ErrorAction SilentlyContinue; "
              "Start-Sleep -Milliseconds 700; "
              f"& {q(setup)} /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RELAUNCH=1 "
              f"('/LOG=' + {q(log_file)})")
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-EncodedCommand", enc]


def _spawn(cmd: list[str]) -> None:
    base = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    breakaway = 0x01000000                     # CREATE_BREAKAWAY_FROM_JOB: outlive this process
    try:
        subprocess.Popen(cmd, creationflags=base | breakaway, close_fds=True)
    except OSError:
        subprocess.Popen(cmd, creationflags=base, close_fds=True)


def install(settings, root: Path = BUNDLE_ROOT, spawn=None) -> dict:
    info = check(root)
    if not info["available"]:
        raise UpdateError({"source": "This copy runs from source — update it with git.",
                           "no_source": "No new build was found.",
                           "up_to_date": "MonoSpace is already up to date."}.get(info["reason"], "No update."))
    d = update_dir(current_build(root))
    new = _read_json(d / SETUP_INFO) or {}
    setup = d / SETUP_NAME
    if new.get("sha256") and sha256(setup) != new["sha256"]:
        raise UpdateError("The new installer doesn't match its build record — it may still be "
                          "building. Try again in a minute.")
    tmp = Path(tempfile.mkdtemp(prefix="monospace-update-"))
    copy = tmp / SETUP_NAME
    shutil.copy2(setup, copy)
    snap = snapshots.take_snapshot(settings, "pre-update")
    log_file = tmp / "install.log"
    (spawn or _spawn)(helper_command(os.getpid(), copy, log_file))
    log.warning("update to build %s: installer %s, snapshot %s, log %s",
                new.get("build"), copy, snap.name if snap else None, log_file)
    return {"ok": True, "build": new.get("build"), "snapshot": snap.name if snap else None,
            "log": str(log_file)}


def quit_app() -> None:
    """Close MonoSpace so the installer can replace it (the launcher's window, else the process)."""
    try:
        if QUIT_HOOK:
            QUIT_HOOK()
            return
    except Exception:
        log.exception("closing the window for the update failed")
    os._exit(0)


def quit_soon(seconds: float = 1.2) -> None:
    t = threading.Timer(seconds, quit_app)
    t.daemon = True
    t.start()
