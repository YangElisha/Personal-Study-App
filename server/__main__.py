"""Start the Drill server:  python -m server  [--open]

Binds to 127.0.0.1 only, on PORT from .env. With PHONE_ACCESS=on it binds 0.0.0.0 so the
phone can reach it over Tailscale; the app itself still refuses every client that is not
this PC or on the tailnet (server/phone.py), and asks those for the PIN. --open opens the app in the browser once the
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


def _print_phone_info(app, settings) -> None:
    hosts, auth = app.state.phone_hosts, app.state.phone_auth
    print("PHONE ACCESS is ON" + (" (home Wi-Fi allowed too)" if settings.phone_allow_lan
                                   else " (Tailscale only)"), flush=True)
    if not hosts.tailscale["installed"]:
        print("  Tailscale is not installed on this PC: the phone cannot reach Drill yet.")
    elif not hosts.tailscale["ips"]:
        print("  Tailscale is installed but not connected (no Tailscale address). Sign in to it.")
    urls = hosts.phone_urls(settings.port)
    if urls:
        print("  Open on the phone:")
        for u in urls:
            print(f"    {u}")
    if not auth.pin_is_set():
        print("  No PIN yet: the phone will be told to set one. Run: python -m server.pin set")
    print(flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server")
    ap.add_argument("--open", action="store_true", help="open the app in the browser")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        settings = load_settings()
    except SettingsError as e:
        print(f"Drill server NOT started: {e}")
        return 2
    url = f"http://localhost:{settings.port}/"
    lock = InstanceLock(settings.lock_file, "server")
    try:
        lock.acquire()
    except AlreadyRunning:
        print(f"Drill is already running: {url}")
        if args.open:
            webbrowser.open(url)
        return 0

    try:
        import uvicorn
        from .app import create_app
        print(f"Drill server: {url}   data: {settings.data_dir}   (Ctrl+C to stop)", flush=True)
        app = create_app(settings)
        bind = "127.0.0.1"
        if settings.phone_access:
            bind = "0.0.0.0"
            _print_phone_info(app, settings)
        if args.open:
            threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
        # proxy_headers off: the client address is the real socket peer, never a header
        uvicorn.run(app, host=bind, port=settings.port, log_level="info",
                    proxy_headers=False)
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
