r"""In-app update (MonoSpace 2026-10-01).

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

GitHub Releases (2026-10-01) — for people who downloaded MonoSpace. A build made with an update repo
(MONOSPACE_UPDATE_REPO or packaging\update-repo.txt, e.g. "YangElisha/MonoSpace") also checks, when
online and allowed, that repo's latest Release (at most every CHECK_EVERY seconds): the release must
carry MonoSpace-Setup.exe and MonoSpace-Setup.json (build, built_at, sha256 — written by build.ps1).
A newer one is offered with its title and notes ("What's new"); installing downloads the installer,
refuses it unless its sha256 matches, then installs exactly like a local update. A failed or offline
check is silent. The project folder (dist\) is checked first, so the developer's own copy keeps
updating from fresh builds without publishing anything.
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
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import snapshots
from .settings import BUNDLE_ROOT

log = logging.getLogger("monospace.update")

INFO_NAME = "build-info.json"
SETUP_NAME = "MonoSpace-Setup.exe"
SETUP_INFO = "MonoSpace-Setup.json"
QUIT_HOOK = None        # set by the launcher: closes the window so the program files can be replaced
GITHUB_API = "https://api.github.com"
CHECK_EVERY = 6 * 3600   # seconds between online checks (GitHub allows 60 unauthenticated calls an hour)
_gh_cache: dict = {"at": 0.0, "repo": "", "result": None}


class UpdateError(Exception):
    pass


def _read_json(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))      # PowerShell may write a BOM
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def current_build(root: Path = BUNDLE_ROOT) -> dict | None:
    override = os.environ.get("MONOSPACE_BUILD_INFO")          # tests and trials only
    return _read_json(Path(override)) if override else _read_json(root / INFO_NAME)


def update_repo(cur: dict | None) -> str:
    return (os.environ.get("MONOSPACE_UPDATE_REPO") or (cur or {}).get("update_repo") or "").strip()


def _newer(new: dict, cur: dict) -> bool:
    return bool(new.get("build")) and new.get("build") != cur.get("build") and \
        str(new.get("built_at", "")) > str(cur.get("built_at", ""))


def _get(url: str, timeout: float = 8.0) -> bytes:
    if not url.startswith("https://") and not url.startswith(os.environ.get("MONOSPACE_UPDATE_API", "https://")):
        raise UpdateError("Updates are only downloaded over https")
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "MonoSpace-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_github(cur: dict, force: bool = False) -> dict | None:
    """The latest GitHub Release, if it is newer than this build; None otherwise (or offline)."""
    repo = update_repo(cur)
    if not repo:
        return None
    now = time.time()
    if not force and _gh_cache["repo"] == repo and now - _gh_cache["at"] < CHECK_EVERY:
        return _gh_cache["result"]
    api = os.environ.get("MONOSPACE_UPDATE_API", GITHUB_API).rstrip("/")
    result = None
    try:
        rel = json.loads(_get(f"{api}/repos/{repo}/releases/latest"))
        assets = {a.get("name"): a.get("browser_download_url") for a in rel.get("assets") or []}
        if assets.get(SETUP_NAME) and assets.get(SETUP_INFO):
            info = json.loads(_get(assets[SETUP_INFO]).decode("utf-8-sig"))
            if _newer(info, cur) and info.get("sha256"):
                result = {"source": "github", "version": str(rel.get("tag_name") or info.get("version") or "").lstrip("vV"),
                          "build": info.get("build"), "built_at": info.get("built_at"), "commit": info.get("commit"),
                          "title": str(rel.get("name") or "")[:200], "notes": str(rel.get("body") or "")[:20000],
                          "published_at": rel.get("published_at"), "page": rel.get("html_url"),
                          "_setup_url": assets[SETUP_NAME], "_sha256": info["sha256"]}
    except (OSError, ValueError, UpdateError, AttributeError, TypeError) as e:
        log.info("update check on GitHub (%s) failed: %s", repo, e)
        if _gh_cache["repo"] == repo:            # offline for now: keep what we knew, try again later
            _gh_cache["at"] = now - CHECK_EVERY + 600
            return _gh_cache["result"]
    _gh_cache.update(at=now, repo=repo, result=result)
    return result


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
    if not info:
        return None
    return {k: info.get(k) for k in ("version", "build", "built_at", "commit", "source", "title", "notes",
                                     "published_at", "page") if info.get(k) is not None}


def _local(cur: dict) -> tuple[dict | None, bool]:
    """(newer build in the project's dist folder, whether such a folder exists)."""
    d = update_dir(cur)
    new = _read_json(d / SETUP_INFO) if d else None
    if not new or not (d / SETUP_NAME).is_file():
        return None, False
    return (dict(new, source="local") if _newer(new, cur) else None), True


def check(root: Path = BUNDLE_ROOT, online: bool = True, force: bool = False) -> dict:
    """{"current", "available", "reason", "repo"}: reason is "source" (running from source),
    "no_source" (nowhere to update from), "up_to_date", or "" when a newer build is available —
    from the project folder first, else (online) from the GitHub Releases of the update repo."""
    cur = current_build(root)
    out = {"current": _public(cur), "available": None, "reason": "", "repo": update_repo(cur)}
    if not cur:
        out["reason"] = "source"
        return out
    local, has_local = _local(cur)
    if local:
        out["available"] = _public(local)
        return out
    gh = check_github(cur, force) if online and out["repo"] else None
    if gh:
        out["available"] = _public(gh)
        return out
    out["reason"] = "up_to_date" if has_local or (online and out["repo"]) else "no_source"
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


def _download(url: str, dest: Path, timeout: float = 120.0) -> None:
    if not url.startswith("https://") and not url.startswith(os.environ.get("MONOSPACE_UPDATE_API", "https://")):
        raise UpdateError("Updates are only downloaded over https")
    req = urllib.request.Request(url, headers={"User-Agent": "MonoSpace-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, dest.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        raise UpdateError(f"The download failed ({e}). Check your connection and try again.") from None


def install(settings, root: Path = BUNDLE_ROOT, spawn=None, online: bool = True) -> dict:
    info = check(root, online=online)
    if not info["available"]:
        raise UpdateError({"source": "This copy runs from source — update it with git.",
                           "no_source": "No new build was found.",
                           "up_to_date": "MonoSpace is already up to date."}.get(info["reason"], "No update."))
    cur = current_build(root)
    tmp = Path(tempfile.mkdtemp(prefix="monospace-update-"))
    copy = tmp / SETUP_NAME
    if info["available"].get("source") == "github":
        gh = check_github(cur) or {}
        _download(gh["_setup_url"], copy)
        if sha256(copy) != gh["_sha256"]:
            shutil.rmtree(tmp, ignore_errors=True)
            raise UpdateError("The downloaded installer doesn't match its release record, so it wasn't "
                              "used. Try again later.")
        new = gh
    else:
        d = update_dir(cur)
        new = _read_json(d / SETUP_INFO) or {}
        setup = d / SETUP_NAME
        if new.get("sha256") and sha256(setup) != new["sha256"]:
            raise UpdateError("The new installer doesn't match its build record — it may still be "
                              "building. Try again in a minute.")
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
