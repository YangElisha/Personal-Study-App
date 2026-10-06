"""MonoSpace desktop app: the entry point of MonoSpace.exe (packaging/monospace.spec).

1. Settings: %APPDATA%\\MonoSpace\\settings.env when frozen (the repo's .env when run from
   source). First run with no settings file: a small dialog asks where the data lives
   (default %USERPROFILE%\\MonoSpaceData), creates that folder and writes settings.env.
   An existing settings file is never overwritten.
2. Starts the server in this process (uvicorn in a thread, 127.0.0.1). If this data folder is
   already served by a MonoSpace server, it just opens another window to it. If the port is
   taken by something else, it uses the next free one and says so.
3. Opens the app in its own native window (pywebview + Microsoft WebView2, built into Windows
   11), so the taskbar shows MonoSpace.exe and its icon. Fallback: Microsoft Edge in app mode
   with a private profile
   (%LOCALAPPDATA%\\MonoSpace\\window). When the last MonoSpace window closes, the server stops
   cleanly (database checkpointed, the data-folder lock released). No Edge: the default
   browser, and a message box that stops MonoSpace when dismissed.

Logs: %LOCALAPPDATA%\\MonoSpace\\logs\\monospace.log (rotated). Errors: a message box.
MONOSPACE_HOME=<folder> moves settings.env, logs and the window profile into <folder>
(tests and the build check use it; the real %APPDATA% is never touched then).

Run from source: python -m server.launcher
"""
from __future__ import annotations

import ctypes
import dataclasses
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

from server import __version__
from server.instance_lock import AlreadyRunning, InstanceLock
from server.settings import (BUNDLE_ROOT, ENV_FILE, FROZEN, REPO_ROOT, SettingsError,
                             _is_inside, desktop_local_dir, load_settings)

APP = "MonoSpace"
ICON = BUNDLE_ROOT / "assets" / "monospace.ico"
log = logging.getLogger("monospace.launcher")

# The keys a new settings.env gets (the same as .env.example, with the chosen DATA_DIR).
SETTINGS_TEMPLATE = """# MonoSpace settings (same keys as the developer .env). Edit with Notepad, then restart.
# Written by MonoSpace on first run; MonoSpace never overwrites this file.

# ---- Where your data lives ----
DATA_DIR={data_dir}
# Automatic database snapshots kept in DATA_DIR\\backups
BACKUP_KEEP=30

# ---- AI (optional). How to connect other AIs: docs/CONNECT-AI.md ----
# The AI on this PC: ollama (any model you pulled), openai (LM Studio, llama.cpp, Jan, vLLM) or off
LOCAL_AI=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_NUM_CTX=8192
# For LOCAL_AI=openai:
# LOCAL_AI_URL=http://localhost:1234/v1
# LOCAL_AI_MODEL=<model name>

# The online AI, through its own program and your own sign-in (no API keys):
# claude (Claude Code), codex (OpenAI Codex CLI), gemini (Gemini CLI), custom or off
ONLINE_AI=claude
CLAUDE_CLI_PATH=claude

# ---- Local server ----
PORT=8765
"""


# ---- small helpers -------------------------------------------------------------------------
def message_box(text: str, kind: str = "info") -> None:
    icon = {"info": 0x40, "warning": 0x30, "error": 0x10}[kind]
    log.info("message box (%s): %s", kind, text)
    if os.name == "nt":
        # MB_OK | icon | MB_SETFOREGROUND | MB_TOPMOST
        r = ctypes.windll.user32.MessageBoxW(None, text, APP, icon | 0x10000 | 0x40000)
        if not r:
            log.error("message box failed (Windows error %d)", ctypes.GetLastError())
    else:
        print(text, file=sys.stderr)


def message_box_async(text: str, kind: str = "info") -> None:
    threading.Thread(target=message_box, args=(text, kind), daemon=True).start()


def setup_logging(local: Path) -> Path:
    if sys.stdout is None:            # the windowed build has no console
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    logs = local / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "monospace.log"
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(process)d %(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    if not FROZEN:
        root.addHandler(logging.StreamHandler())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return path


def health(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url + "api/health", timeout=timeout) as r:
            if r.status == 200:
                d = json.loads(r.read().decode("utf-8"))
                return d if isinstance(d, dict) and d.get("app") == "drill" else None
    except (OSError, ValueError):
        pass
    return None


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


# ---- first run -----------------------------------------------------------------------------
def default_data_dir() -> Path:
    home = os.environ.get("MONOSPACE_HOME", "").strip()
    if home:                                   # tests: never the real profile folder
        return Path(home).resolve() / "MonoSpaceData"
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "MonoSpaceData"


def first_run_dialog(settings_file: Path) -> Path | None:
    """Ask where the data lives; create it; write settings_file. None = cancelled."""
    import tkinter as tk
    from tkinter import filedialog, font, ttk

    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    chosen = {"dir": default_data_dir(), "ok": False}
    root = tk.Tk()
    root.title(f"{APP}: first start")
    try:
        root.iconbitmap(default=str(ICON))
    except tk.TclError:
        pass
    root.resizable(False, False)
    wrap = int(460 * root.winfo_fpixels("1i") / 96)       # 460 px at 100% scaling
    f = ttk.Frame(root, padding=18)
    f.grid(sticky="nsew")
    bold = font.nametofont("TkDefaultFont").copy()
    bold.configure(weight="bold", size=bold.cget("size") + 2)
    ttk.Label(f, text="Welcome to MonoSpace", font=bold).grid(row=0, column=0, columnspan=2,
                                                               sticky="w")
    ttk.Label(f, wraplength=wrap, justify="left", text=(
        "Your decks, progress, automatic backups and module PDFs will be kept in this "
        "folder on this PC. You can choose another folder (for example one that OneDrive "
        "backs up). Uninstalling MonoSpace never deletes it.")).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(8, 10))
    path_var = tk.StringVar(value=str(chosen["dir"]))
    ttk.Entry(f, textvariable=path_var, width=58, state="readonly").grid(row=2, column=0,
                                                                         sticky="ew")
    err_var = tk.StringVar()

    def change():
        d = filedialog.askdirectory(parent=root, title="Where should MonoSpace keep your data?",
                                    initialdir=str(Path(path_var.get()).parent), mustexist=False)
        if d:
            path_var.set(str(Path(d)))
            err_var.set("")

    def start(_evt=None):
        d = Path(path_var.get()).resolve()
        if _is_inside(d, REPO_ROOT.resolve()):
            err_var.set("That folder is inside the MonoSpace program folder. Choose another one.")
            return
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            err_var.set(f"Could not create that folder: {e.strerror or e}")
            return
        chosen["dir"], chosen["ok"] = d, True
        root.destroy()

    ttk.Button(f, text="Change…", command=change).grid(row=2, column=1, padx=(8, 0))
    ttk.Label(f, textvariable=err_var, foreground="#b00020", wraplength=wrap).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
    b = ttk.Button(f, text="Start", command=start, default="active")
    b.grid(row=4, column=1, sticky="e", pady=(10, 0))
    b.focus_set()
    root.bind("<Return>", start)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    root.attributes("-topmost", True)
    root.after(600, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()
    if not chosen["ok"]:
        return None
    write_settings_file(settings_file, chosen["dir"])
    return chosen["dir"]


def write_settings_file(settings_file: Path, data_dir: Path) -> bool:
    """Create settings_file for data_dir. Never overwrites: False if it already exists."""
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(settings_file, "x", encoding="utf-8", newline="\r\n") as fh:
            fh.write(SETTINGS_TEMPLATE.format(data_dir=data_dir))
    except FileExistsError:
        log.info("first run: %s already exists; left as it is", settings_file)
        return False
    log.info("first run: wrote %s with DATA_DIR=%s", settings_file, data_dir)
    return True


# ---- the window ----------------------------------------------------------------------------
def find_edge() -> str | None:
    cands = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    cands += [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
              Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def builds_running(url: str) -> int:
    """How many deck builds the open pages have running or queued (0 if the server can't say)."""
    try:
        with urllib.request.urlopen(url + "api/builds", timeout=2) as r:
            return max(0, int(json.loads(r.read().decode("utf-8")).get("active", 0)))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def ok_to_close(url: str) -> bool:
    """Asked when the window is closing: a build in progress would be lost, so check first."""
    n = builds_running(url)
    if not n or os.name != "nt":
        return True
    what = "A deck is still being built" if n == 1 else f"{n} decks are still being built or queued"
    # MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON2 | MB_SETFOREGROUND | MB_TOPMOST; IDOK = 1
    r = ctypes.windll.user32.MessageBoxW(
        None, f"{what}.\n\nClosing MonoSpace stops it, and anything not finished is lost "
        "(finished decks are safe).\n\nClose anyway?", APP, 0x1 | 0x30 | 0x100 | 0x10000 | 0x40000)
    log.info("close during %d build(s): %s", n, "closed" if r == 1 else "kept open")
    return r == 1


def package_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:                          # not recorded in the frozen app
        return "?"


# How the window opens (2026-10-06): filling the screen, not parked in a corner. It used to be a
# fixed 1400x900 wherever Windows felt like putting it. MONOSPACE_WINDOW=window opens it as a
# normal window instead; either way the restored size is centred on the screen you work on.
WINDOW_MODE = os.environ.get("MONOSPACE_WINDOW", "maximized").strip().lower()


def work_area() -> tuple[int, int, int, int]:
    """The usable desktop (x, y, width, height) — the screen minus the taskbar."""
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):      # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def window_box(width: int, height: int) -> tuple[int, int, int | None, int | None]:
    """The size to open at, and the top-left that centres it. (w, h, None, None) if unknown."""
    try:
        ox, oy, sw, sh = work_area()
        if sw < 200 or sh < 200:
            return width, height, None, None
        w = max(900, min(width, sw - 80))
        h = max(600, min(height, sh - 80))
        return w, h, ox + (sw - w) // 2, oy + (sh - h) // 2
    except Exception:                                   # not Windows, or no desktop to measure
        return width, height, None, None


def native_window(url: str, profile: Path) -> bool:
    """Show the app in a native WebView2 window; blocks until it closes. False = unavailable."""
    try:
        import webview
    except Exception as e:                      # not installed / broken
        log.warning("native window unavailable: %r", e)
        return False
    try:
        profile.mkdir(parents=True, exist_ok=True)
        webview.settings["ALLOW_DOWNLOADS"] = True          # "Download backup"
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        w, h, x, y = window_box(1400, 900)
        win = webview.create_window(APP, url, width=w, height=h, min_size=(900, 600),
                                    maximized=WINDOW_MODE != "window", x=x, y=y,
                                    background_color="#000000", text_select=True)
        win.events.closing += lambda: ok_to_close(url)      # False keeps the window open
        from server import update
        update.QUIT_HOOK = win.destroy                       # an update closes the window, then installs
        log.info("window: native (pywebview %s)", package_version("pywebview"))
        webview.start(gui="edgechromium", icon=str(ICON), private_mode=False,
                      storage_path=str(profile))
        return True
    except Exception:
        log.exception("native window failed; falling back to Edge")
        return False


def open_window(url: str, profile: Path) -> bool:
    """Open an app window. True = an Edge app window (with profile), False = default browser."""
    edge = find_edge()
    if edge:
        profile.mkdir(parents=True, exist_ok=True)
        cmd = [edge, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
               "--no-default-browser-check", "--disable-sync", "--disable-features=msEdgeSidebarV2"]
        log.info("window: %s", subprocess.list2cmdline(cmd))
        subprocess.Popen(cmd, close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    log.warning("Microsoft Edge not found; opening the default browser")
    webbrowser.open(url)
    return False


def window_processes(profile: Path) -> list:
    """The Edge browser processes (not renderers/helpers) using the MonoSpace window profile."""
    import psutil
    key = os.path.normcase(f"--user-data-dir={profile}")
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() != "msedge.exe":
                continue
            cl = p.info["cmdline"] or []
            if any(a.startswith("--type=") for a in cl):
                continue
            if any(os.path.normcase(a) == key for a in cl):
                out.append(p)
        except Exception:
            continue
    return out


def wait_for_window_to_close(profile: Path, appear_timeout: float = 30.0) -> bool:
    """Block until no MonoSpace window process is left. False = none ever appeared."""
    end = time.time() + appear_timeout
    while not window_processes(profile):
        if time.time() > end:
            return False
        time.sleep(0.5)
    log.info("window is open")
    while True:
        procs = window_processes(profile)
        if not procs:
            return True
        import psutil
        psutil.wait_procs(procs, timeout=2)


# ---- the server ----------------------------------------------------------------------------
class ServerThread:
    def __init__(self, settings):
        import uvicorn
        from server.app import create_app
        self.config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=settings.port,
                                     log_config=None, log_level="info", access_log=False,
                                     proxy_headers=False,
                                     lifespan="on")
        self.server = uvicorn.Server(self.config)
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name="uvicorn", daemon=True)

    def _run(self):
        try:
            self.server.run()
        except BaseException as e:          # uvicorn calls sys.exit(1) when it cannot bind
            self.error = e
            log.error("server stopped with an error: %r", e)

    def start(self, url: str, timeout: float = 60.0) -> None:
        self.thread.start()
        end = time.time() + timeout
        while time.time() < end:
            if self.server.started and health(url):
                return
            if not self.thread.is_alive():
                raise RuntimeError(f"the server did not start ({self.error!r}); see the log")
            time.sleep(0.2)
        raise RuntimeError("the server did not answer within a minute; see the log")

    def stop(self, timeout: float = 30.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout)
        if self.thread.is_alive():
            log.error("server did not stop within %.0fs", timeout)
        else:
            log.info("server stopped")


def running_note(local: Path) -> Path:
    return local / "running.json"


def running_pid(settings, local: Path) -> int | None:
    """The desktop MonoSpace process serving this data folder, from its running note."""
    try:
        d = json.loads(running_note(local).read_text(encoding="utf-8"))
        if os.path.normcase(d.get("data_dir", "")) == os.path.normcase(str(settings.data_dir)):
            return int(d["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def focus_window(pid: int, wait: float = 5.0) -> bool:
    """Bring the MonoSpace window of process `pid` to the front. False = it has none (yet).

    A second launch does this instead of opening a second window: two windows share one
    server, and closing the first stops that server under the second."""
    if os.name != "nt" or not pid:
        return False
    u32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        owner = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and u32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 256)
            if buf.value == APP:
                found.append(hwnd)
                return False
        return True

    end = time.time() + wait                 # it may still be opening (a double-click)
    while not found:
        u32.EnumWindows(each, None)
        if found or time.time() >= end:
            break
        time.sleep(0.25)
    if not found:
        return False
    h = ctypes.c_void_p(found[0])
    if u32.IsIconic(h):
        u32.ShowWindow(h, 9)                 # SW_RESTORE
    u32.SetForegroundWindow(h)
    return True


def find_running(settings, local: Path) -> str | None:
    """URL of the MonoSpace server already serving this data folder, if it answers."""
    try:
        d = json.loads(running_note(local).read_text(encoding="utf-8"))
        if os.path.normcase(d.get("data_dir", "")) == os.path.normcase(str(settings.data_dir)):
            url = f"http://localhost:{int(d['port'])}/"
            if health(url):
                return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    url = f"http://localhost:{settings.port}/"        # e.g. start.bat's server
    return url if health(url) else None


def pick_port(port: int) -> tuple[int, str | None]:
    if not port_in_use(port):
        return port, None
    who = ("another MonoSpace server (a different data folder)"
           if health(f"http://localhost:{port}/") else "another program")
    for p in range(port + 1, port + 100):
        if not port_in_use(p):
            return p, f"Port {port} is used by {who}, so MonoSpace is using port {p} this time."
    raise RuntimeError(f"No free port between {port} and {port + 99}.")


# ---- main ----------------------------------------------------------------------------------
def run() -> int:
    local = desktop_local_dir()
    log_path = setup_logging(local)
    log.info("MonoSpace %s starting (frozen=%s, exe=%s, settings=%s)", __version__, FROZEN,
             sys.executable, ENV_FILE)

    if not ENV_FILE.is_file():
        if not FROZEN:
            message_box(f"No settings file: {ENV_FILE}. Copy .env.example to .env first.", "error")
            return 2
        if first_run_dialog(ENV_FILE) is None:
            log.info("first run cancelled")
            return 0
    try:
        settings = load_settings()
    except SettingsError as e:
        message_box(f"MonoSpace could not start:\n\n{e}\n\nSettings file: {ENV_FILE}", "error")
        return 2
    profile = local / "window"

    lock = InstanceLock(settings.lock_file, "desktop")
    try:
        lock.acquire()
    except AlreadyRunning:
        url = find_running(settings, local)
        if url:
            if focus_window(running_pid(settings, local) or 0):
                log.info("already running at %s; brought its window to the front", url)
                return 0
            log.info("already running at %s; opening another window", url)
            if native_window(url, profile / "native"):
                return 0
            if not open_window(url, profile):
                message_box_async(f"MonoSpace is already running at {url}")
                time.sleep(5)
            return 0
        message_box("Another MonoSpace program (an import or restore tool) is using the data "
                    f"folder\n{settings.data_dir}\nTry again when it has finished.", "error")
        return 1

    server = None
    try:
        port, note = pick_port(settings.port)
        settings = dataclasses.replace(settings, port=port)
        url = f"http://localhost:{port}/"
        server = ServerThread(settings)
        server.start(url)
        log.info("server ready at %s, data %s", url, settings.data_dir)
        running_note(local).write_text(json.dumps(
            {"pid": os.getpid(), "port": port, "data_dir": str(settings.data_dir),
             "version": __version__}), encoding="utf-8")
        if note:
            log.warning(note)
            message_box_async(note, "warning")
        if native_window(url, profile / "native"):
            pass
        elif open_window(url, profile):
            from server import update
            update.QUIT_HOOK = lambda: [p.terminate() for p in window_processes(profile)]
            if not wait_for_window_to_close(profile):
                log.warning("no Edge window appeared; falling back to the default browser")
                webbrowser.open(url)
                message_box(f"MonoSpace is open in your browser at {url}\n\n"
                            "Click OK to stop MonoSpace.")
        else:
            message_box(f"MonoSpace is open in your browser at {url}\n(Microsoft Edge was not "
                        "found, so it could not open in its own window.)\n\n"
                        "Keep this message open while you study. Click OK to stop MonoSpace.")
        log.info("window closed; stopping")
        return 0
    except Exception as e:
        log.exception("startup failed")
        message_box(f"MonoSpace could not start:\n\n{e}\n\nLog: {log_path}", "error")
        return 1
    finally:
        if server is not None:
            server.stop()
        try:
            running_note(local).unlink()
        except OSError:
            pass
        lock.release()
        log.info("MonoSpace stopped")


def main() -> int:
    try:
        return run()
    except Exception:
        tb = traceback.format_exc()
        try:
            log.error("fatal: %s", tb)
        finally:
            message_box(f"MonoSpace hit an unexpected error:\n\n{tb[-1500:]}", "error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
