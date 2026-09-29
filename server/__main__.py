"""Start the MonoSpace server:  python -m server  [--open]

Binds to 127.0.0.1 only, on PORT from .env. --open opens the app in the browser once the
server answers (start.bat uses it). If the server is already running, --open just opens
the browser.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import urllib.request
import webbrowser

from .instance_lock import AlreadyRunning, InstanceLock
from .settings import SettingsError, load_settings


def _open_when_ready(url: str, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1) as r:
                if r.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(0.3)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server")
    ap.add_argument("--open", action="store_true", help="open the app in the browser")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        settings = load_settings()
    except SettingsError as e:
        print(f"MonoSpace server NOT started: {e}")
        return 2
    url = f"http://localhost:{settings.port}/"
    lock = InstanceLock(settings.lock_file, "server")
    try:
        lock.acquire()
    except AlreadyRunning:
        print(f"MonoSpace is already running: {url}")
        if args.open:
            webbrowser.open(url)
        return 0

    try:
        import uvicorn
        from .app import create_app
        print(f"MonoSpace server: {url}   data: {settings.data_dir}   (Ctrl+C to stop)", flush=True)
        if args.open:
            threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
        # 127.0.0.1 only; proxy_headers off: the client address is the real socket peer
        uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port,
                    log_level="info", proxy_headers=False)
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
