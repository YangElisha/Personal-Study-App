"""Phase 8: phone access over Tailscale, behind a PIN.

PHONE_ACCESS=off (default): the server binds 127.0.0.1 and answers loopback clients only.
PHONE_ACCESS=on: it binds 0.0.0.0, but answers only
  - loopback (this PC; never asked for a PIN),
  - Tailscale addresses 100.64.0.0/10 and fd7a:115c:a1e0::/48,
  - with PHONE_ALLOW_LAN=on also the private home-network ranges;
every other client gets 403 before anything else happens. Non-loopback clients need a
session cookie, obtained by entering the PIN (set on the PC: python -m server.pin set).

The PIN hash and the sessions live in DATA_DIR\\phone-access.db, never in the repo and not
in drill.db (so restoring a snapshot cannot bring back an old PIN or revoked sessions).
Only hashes are stored: scrypt for the PIN, SHA-256 for session tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("drill.phone")

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
TAILSCALE_NETS = (ipaddress.ip_network("100.64.0.0/10"),
                  ipaddress.ip_network("fd7a:115c:a1e0::/48"))
LAN_NETS = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("fe80::/10"),
            ipaddress.ip_network("fc00::/7"))

COOKIE = "drill_session"
SESSION_DAYS = 30
MAX_FAILS = 5
LOCKOUT_SECONDS = 15 * 60
MIN_PIN_DIGITS = 6
LOGIN_PATH = "/api/phone/login"
LOGOUT_PATH = "/api/phone/logout"
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---- who is asking ------------------------------------------------------------------------
def client_ip(addr: str | None):
    """The client's address as an ip_address (IPv4-mapped IPv6 unwrapped), or None."""
    if not addr:
        return None
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def is_local(ip) -> bool:
    return ip is not None and ip.is_loopback


def client_allowed(ip, phone_access: bool, allow_lan: bool) -> bool:
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    if not phone_access:
        return False
    if any(ip.version == n.version and ip in n for n in TAILSCALE_NETS):
        return True
    return allow_lan and any(ip.version == n.version and ip in n for n in LAN_NETS)


def split_host(host_header: str) -> tuple[str, str]:
    """'Host' header -> (host, port). Handles '[v6]:port'. Host is lowercased, no brackets,
    no trailing dot."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        end = h.find("]")
        if end < 0:
            return h, ""
        host, rest = h[1:end], h[end + 1:]
        return host, rest[1:] if rest.startswith(":") else ""
    if h.count(":") > 1:                     # bare IPv6 without port (not valid, but be safe)
        return h, ""
    host, _, port = h.partition(":")
    return host.rstrip("."), port


def origin_for(host: str, port: str) -> str:
    h = f"[{host}]" if ":" in host else host
    return f"http://{h}" + (f":{port}" if port else "")


# ---- this PC's names on the tailnet ---------------------------------------------------------
def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        p = Path(base) / "Tailscale" / "tailscale.exe"
        if p.is_file():
            return str(p)
    return None


def detect_tailscale(timeout: float = 4.0) -> dict:
    """{'installed': bool, 'ips': [...], 'names': [...]} from the tailscale CLI. Never raises."""
    out = {"installed": False, "ips": [], "names": []}
    exe = _tailscale_exe()
    if not exe:
        return out
    out["installed"] = True
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def run(*args):
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                               creationflags=flags)
            return r.stdout if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    for fam in ("-4", "-6"):
        for line in run("ip", fam).split():
            if client_ip(line.strip()) is not None:
                out["ips"].append(str(client_ip(line.strip())))
    try:
        st = json.loads(run("status", "--json") or "{}")
    except ValueError:
        st = {}
    me = st.get("Self") or {}
    for ip in me.get("TailscaleIPs") or []:
        if client_ip(ip) is not None and str(client_ip(ip)) not in out["ips"]:
            out["ips"].append(str(client_ip(ip)))
    dns = (me.get("DNSName") or "").strip().rstrip(".").lower()
    if dns:
        out["names"].append(dns)                      # pc.tailnet-name.ts.net
        out["names"].append(dns.split(".", 1)[0])     # MagicDNS short name: pc
    elif me.get("HostName"):
        out["names"].append(str(me["HostName"]).lower())
    return out


def lan_ips() -> list[str]:
    """This PC's own private addresses (for PHONE_ALLOW_LAN)."""
    ips = set()
    try:
        for fam, *_rest, sa in socket.getaddrinfo(socket.gethostname(), None):
            ip = client_ip(sa[0])
            if ip is not None and any(ip.version == n.version and ip in n for n in LAN_NETS[:3]):
                ips.add(str(ip))
    except OSError:
        pass
    try:  # the address used for the default route (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = client_ip(s.getsockname()[0])
            if ip is not None and any(ip in n for n in LAN_NETS[:3]):
                ips.add(str(ip))
    except OSError:
        pass
    return sorted(ips)


@dataclass
class HostList:
    """Which Host header values this server answers to."""
    phone_access: bool
    allow_lan: bool
    extra: tuple = ()
    detect: bool = True
    tailscale: dict = field(default_factory=lambda: {"installed": False, "ips": [], "names": []})
    lan: list = field(default_factory=list)
    _checked: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def refresh(self) -> None:
        if not (self.phone_access and self.detect):
            return
        with self._lock:
            self.tailscale = detect_tailscale()
            self.lan = lan_ips() if self.allow_lan else []
            self._checked = time.monotonic()

    def allowed(self) -> set[str]:
        hosts = set(LOCAL_HOSTS)
        if self.phone_access:
            hosts.update(self.extra)
            hosts.update(self.tailscale["ips"])
            hosts.update(self.tailscale["names"])
            hosts.update(self.lan)
        return hosts

    def stale(self, seconds: float = 30.0) -> bool:
        return self.phone_access and self.detect and time.monotonic() - self._checked > seconds

    def phone_urls(self, port: int) -> list[str]:
        names = [h for h in self.tailscale["names"] if "." in h] + list(self.extra)
        ips = [i for i in self.tailscale["ips"] if ":" not in i] + self.lan
        return [origin_for(h, str(port)) + "/" for h in dict.fromkeys(names + ips)]


# ---- PIN and sessions (DATA_DIR\phone-access.db) --------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS pin (
  id INTEGER PRIMARY KEY AUTOINCREMENT, salt TEXT NOT NULL, hash TEXT NOT NULL,
  params TEXT NOT NULL, set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_sha256 TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  client_ip TEXT, user_agent TEXT, last_seen TEXT, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS auth_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, client_ip TEXT, event TEXT NOT NULL
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    c.execute("PRAGMA busy_timeout=10000")
    c.executescript(SCHEMA)
    return c


def _hash_pin(pin: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=params["n"], r=params["r"],
                          p=params["p"], dklen=params["dklen"], maxmem=64 * 1024 * 1024)


def valid_pin_format(pin: str) -> bool:
    return pin.isascii() and pin.isdigit() and len(pin) >= MIN_PIN_DIGITS


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PhoneAuth:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._fails: dict[str, list] = {}           # ip -> [count, locked_until]
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        return _connect(self.db_path)

    def event(self, ip: str | None, what: str) -> None:
        c = self.conn()
        try:
            c.execute("INSERT INTO auth_events(at, client_ip, event) VALUES (?,?,?)",
                      (now_iso(), ip, what))
        finally:
            c.close()

    # PIN
    def pin_is_set(self) -> bool:
        if not self.db_path.is_file():
            return False
        c = self.conn()
        try:
            return c.execute("SELECT 1 FROM pin LIMIT 1").fetchone() is not None
        finally:
            c.close()

    def set_pin(self, pin: str) -> int:
        """Store a new PIN (the old row is kept, the newest wins) and revoke every session.
        Returns the number of sessions revoked."""
        if not valid_pin_format(pin):
            raise ValueError(f"The PIN must be at least {MIN_PIN_DIGITS} digits (0-9 only).")
        salt = secrets.token_bytes(16)
        h = _hash_pin(pin, salt, SCRYPT)
        c = self.conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT INTO pin(salt, hash, params, set_at) VALUES (?,?,?,?)",
                      (salt.hex(), h.hex(), json.dumps({"alg": "scrypt", **SCRYPT}), now_iso()))
            n = c.execute("UPDATE sessions SET revoked_at=? WHERE revoked_at IS NULL",
                          (now_iso(),)).rowcount
            c.execute("INSERT INTO auth_events(at, client_ip, event) VALUES (?,?,?)",
                      (now_iso(), None, f"pin set; {n} session(s) revoked"))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return n

    def check_pin(self, pin: str) -> bool:
        c = self.conn()
        try:
            row = c.execute("SELECT salt, hash, params FROM pin ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            c.close()
        if row is None:
            return False
        params = json.loads(row[2])
        got = _hash_pin(pin, bytes.fromhex(row[0]), params)
        return hmac.compare_digest(got, bytes.fromhex(row[1]))

    # sessions
    def new_session(self, ip: str | None, user_agent: str | None) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        c = self.conn()
        try:
            c.execute("INSERT INTO sessions(token_sha256, created_at, expires_at, client_ip, "
                      "user_agent, last_seen) VALUES (?,?,?,?,?,?)",
                      (_token_hash(token), now_iso(),
                       (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds"),
                       ip, (user_agent or "")[:300], now_iso()))
        finally:
            c.close()
        return token

    def session_valid(self, token: str | None) -> bool:
        if not token or len(token) > 200 or not self.db_path.is_file():
            return False
        c = self.conn()
        try:
            row = c.execute("SELECT expires_at, revoked_at FROM sessions WHERE token_sha256=?",
                            (_token_hash(token),)).fetchone()
        finally:
            c.close()
        if row is None or row[1] is not None:
            return False
        return datetime.fromisoformat(row[0]) > datetime.now(timezone.utc)

    def revoke(self, token: str | None) -> bool:
        if not token:
            return False
        c = self.conn()
        try:
            return c.execute("UPDATE sessions SET revoked_at=? WHERE token_sha256=? AND "
                             "revoked_at IS NULL", (now_iso(), _token_hash(token))).rowcount > 0
        finally:
            c.close()

    def revoke_all(self) -> int:
        c = self.conn()
        try:
            n = c.execute("UPDATE sessions SET revoked_at=? WHERE revoked_at IS NULL",
                          (now_iso(),)).rowcount
            c.execute("INSERT INTO auth_events(at, client_ip, event) VALUES (?,?,?)",
                      (now_iso(), None, f"revoke-all: {n} session(s)"))
            return n
        finally:
            c.close()

    def active_sessions(self) -> list:
        if not self.db_path.is_file():
            return []
        c = self.conn()
        try:
            rows = c.execute("SELECT created_at, expires_at, client_ip, user_agent, last_seen "
                             "FROM sessions WHERE revoked_at IS NULL ORDER BY created_at").fetchall()
        finally:
            c.close()
        now = datetime.now(timezone.utc)
        return [r for r in rows if datetime.fromisoformat(r[1]) > now]

    # rate limit (in memory; a server restart clears it)
    def locked_for(self, ip: str) -> int:
        with self._lock:
            f = self._fails.get(ip)
            if not f or not f[1]:
                return 0
            left = f[1] - time.monotonic()
            if left <= 0:
                self._fails.pop(ip, None)
                return 0
            return int(left) + 1

    def record_failure(self, ip: str) -> int:
        """Returns the lockout length in seconds if this failure locked the client, else 0."""
        with self._lock:
            f = self._fails.setdefault(ip, [0, 0.0])
            f[0] += 1
            if f[0] >= MAX_FAILS:
                f[1] = time.monotonic() + LOCKOUT_SECONDS
                locked = LOCKOUT_SECONDS
            else:
                locked = 0
        if locked:
            log.warning("phone access: %s locked out for 15 minutes after %d wrong PINs",
                        ip, MAX_FAILS)
            self.event(ip, f"locked out after {MAX_FAILS} wrong PINs")
        else:
            log.warning("phone access: wrong PIN from %s (%d/%d)", ip, f[0], MAX_FAILS)
            self.event(ip, "wrong PIN")
        return locked

    def clear_failures(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


# ---- the pages a phone sees before it is signed in -----------------------------------------
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Drill</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f4f1ea;color:#222}
main{width:100%;max-width:22rem;padding:1.5rem}
h1{font-size:1.6rem;margin:0 0 .25rem}
p{line-height:1.45;margin:.5rem 0 1rem}
input{width:100%;font-size:1.6rem;letter-spacing:.3em;text-align:center;padding:.7rem;
border:2px solid #999;border-radius:.6rem;background:#fff}
input:focus{outline:none;border-color:#2f5d8a}
button{width:100%;margin-top:1rem;font-size:1.15rem;padding:.9rem;border:0;border-radius:.6rem;
background:#2f5d8a;color:#fff;min-height:48px}
.msg{color:#a02020;font-weight:600}
@media (prefers-color-scheme:dark){body{background:#1c1c1e;color:#eee}
input{background:#2c2c2e;color:#eee;border-color:#555}}
</style></head><body><main>{BODY}</main></body></html>"""


def _page(body: str) -> str:
    return _PAGE.replace("{BODY}", body)


def login_page(message: str = "", locked: bool = False) -> str:
    import html
    msg = f'<p class="msg" role="alert">{html.escape(message)}</p>' if message else ""
    if locked:
        return _page(f"<h1>Drill</h1>{msg}<p>Try again later.</p>")
    form = (f'<form method="post" action="{LOGIN_PATH}">'
            '<label for="pin"><p>Enter the PIN set on the PC.</p></label>'
            '<input id="pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]*" '
            'autocomplete="current-password" autofocus required minlength="6">'
            '<button type="submit">Open Drill</button></form>')
    return _page(f"<h1>Drill</h1>{msg}{form}")


def no_pin_page() -> str:
    return _page("<h1>Drill</h1><p><b>Set a PIN on the PC first.</b></p>"
                    "<p>On the PC, in the Drill folder, run:<br><code>python -m server.pin set</code>"
                    "</p><p>Then reload this page.</p>")
