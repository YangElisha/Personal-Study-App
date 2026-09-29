"""Phase 9: approved accounts, sessions and sign-in events (DATA_DIR\\accounts.db).

One database per person:
- the account allowed with --existing-data uses DATA_DIR itself (Elisha: the existing
  drill.db, modules\\ and backups\\, used in place; nothing is copied, moved or changed);
- every other account gets DATA_DIR\\users\\<id>\\ (drill.db, modules\\, backups\\, import\\).

accounts.db is separate from every drill.db, so restoring a snapshot can never bring back a
revoked session. Only SHA-256 hashes of session tokens are stored. Nothing here is ever
deleted: disallowing an account or revoking a session marks it, and the account's data stays.

CLI (works while the server runs):
  python -m server.accounts allow <email> [--existing-data]
  python -m server.accounts disallow <email>
  python -m server.accounts list
  python -m server.accounts sessions [--email <email>]
  python -m server.accounts revoke-all [--email <email>]
  python -m server.accounts events [--email <email>] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import db

SESSION_SECONDS = 7 * 24 * 3600        # absolute: a session never gets longer by being used
COOKIE = "drill_session"               # the same name the phone PIN sessions use
LAST_SEEN_EVERY = 60                   # write last_seen at most once a minute per session
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,                     -- stable; names the folder DATA_DIR/users/<id>
  email TEXT NOT NULL UNIQUE,              -- lower case
  existing_data INTEGER NOT NULL DEFAULT 0,-- 1: this account uses DATA_DIR itself
  allowed INTEGER NOT NULL DEFAULT 1,
  google_sub TEXT,                         -- Google's stable account id, bound at first sign-in
  created_at TEXT NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS users_one_existing ON users(existing_data)
  WHERE existing_data = 1;
CREATE TABLE IF NOT EXISTS sessions (
  public_id TEXT PRIMARY KEY,              -- shown to the account page; not a credential
  token_sha256 TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  method TEXT NOT NULL,                    -- google | pin
  created INTEGER NOT NULL,                -- unix seconds
  expires INTEGER NOT NULL,
  last_seen INTEGER,
  client_ip TEXT,
  user_agent TEXT,
  revoked INTEGER,
  revoked_reason TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS sign_in_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL,
  event TEXT NOT NULL,                     -- signed_in | refused | signed_out
  method TEXT,                             -- google | pin | cli
  email TEXT,
  user_id TEXT,
  reason TEXT,
  client_ip TEXT,
  user_agent TEXT
);
"""


class AccountError(Exception):
    pass


def iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat().replace("+00:00", "Z")


def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e):
        raise AccountError(f"{email!r} is not an email address.")
    return e


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def device_label(ua: str | None) -> str:
    """'Edge on Windows', 'Safari on iPhone', ... from a User-Agent. Best effort."""
    u = ua or ""
    if not u:
        return "Unknown device"
    if "iPhone" in u:
        os_ = "iPhone"
    elif "iPad" in u:
        os_ = "iPad"
    elif "Android" in u:
        os_ = "Android"
    elif "Windows" in u:
        os_ = "Windows"
    elif "Mac OS X" in u or "Macintosh" in u:
        os_ = "Mac"
    elif "CrOS" in u:
        os_ = "ChromeOS"
    elif "Linux" in u:
        os_ = "Linux"
    else:
        os_ = ""
    if "Edg/" in u or "EdgA/" in u or "EdgiOS/" in u:
        br = "Edge"
    elif "OPR/" in u or "Opera" in u:
        br = "Opera"
    elif "Firefox/" in u or "FxiOS/" in u:
        br = "Firefox"
    elif "Chrome/" in u or "CriOS/" in u:
        br = "Chrome"
    elif "Safari/" in u:
        br = "Safari"
    else:
        br = "Browser"
    return f"{br} on {os_}" if os_ else br


@dataclass(frozen=True)
class User:
    id: str
    email: str
    existing_data: bool
    allowed: bool
    google_sub: str | None

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "existing_data": self.existing_data}


@dataclass(frozen=True)
class Session:
    public_id: str
    user: User
    method: str
    created: int
    expires: int
    last_seen: int | None
    client_ip: str | None
    user_agent: str | None

    def public(self, current_id: str | None = None) -> dict:
        return {"id": self.public_id, "method": self.method,
                "device": device_label(self.user_agent), "user_agent": self.user_agent or "",
                "client_ip": self.client_ip, "created_at": iso(self.created),
                "last_seen_at": iso(self.last_seen), "expires_at": iso(self.expires),
                "current": self.public_id == current_id}


def _user(row) -> User | None:
    if row is None:
        return None
    return User(id=row[0], email=row[1], existing_data=bool(row[2]), allowed=bool(row[3]),
                google_sub=row[4])


_USER_COLS = "id, email, existing_data, allowed, google_sub"


class Accounts:
    def __init__(self, db_path: Path, clock=time.time):
        self.db_path = Path(db_path)
        self.clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self.conn().close()                      # create the file and tables now

    def now(self) -> int:
        return int(self.clock())

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None,
                            check_same_thread=False)
        c.execute("PRAGMA busy_timeout=10000")
        c.executescript(SCHEMA)
        return c

    def _q(self, sql: str, args=()) -> list:
        c = self.conn()
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def _x(self, sql: str, args=()) -> int:
        c = self.conn()
        try:
            return c.execute(sql, args).rowcount
        finally:
            c.close()

    # ---- users -------------------------------------------------------------------------
    def user_by_email(self, email: str) -> User | None:
        try:
            e = norm_email(email)
        except AccountError:
            return None
        rows = self._q(f"SELECT {_USER_COLS} FROM users WHERE email=?", (e,))
        return _user(rows[0] if rows else None)

    def user_by_id(self, uid: str) -> User | None:
        rows = self._q(f"SELECT {_USER_COLS} FROM users WHERE id=?", (uid,))
        return _user(rows[0] if rows else None)

    def users(self) -> list[User]:
        return [_user(r) for r in self._q(f"SELECT {_USER_COLS} FROM users ORDER BY created_at")]

    def allow(self, email: str, existing_data: bool = False) -> tuple[User, str]:
        """Approve an email. Returns (user, 'added'|'re-allowed'|'unchanged'). Never changes
        which data an existing account uses."""
        e = norm_email(email)
        now = iso(self.now())
        c = self.conn()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                row = c.execute(f"SELECT {_USER_COLS} FROM users WHERE email=?", (e,)).fetchone()
                u = _user(row)
                if u is not None and existing_data != u.existing_data:
                    raise AccountError(
                        f"{e} is already set up with "
                        f"{'DATA_DIR itself' if u.existing_data else 'its own folder users/' + u.id}. "
                        "Changing which data an account uses is not done automatically; "
                        "nothing changed.")
                if existing_data and u is None:
                    other = c.execute("SELECT email FROM users WHERE existing_data=1").fetchone()
                    if other:
                        raise AccountError(f"{other[0]} already uses the existing data in "
                                           "DATA_DIR. Only one account can; nothing changed.")
                if u is None:
                    uid = "u" + secrets.token_hex(8)
                    c.execute("INSERT INTO users(id, email, existing_data, allowed, created_at, "
                              "changed_at) VALUES (?,?,?,1,?,?)",
                              (uid, e, 1 if existing_data else 0, now, now))
                    status = "added"
                elif not u.allowed:
                    c.execute("UPDATE users SET allowed=1, changed_at=? WHERE id=?", (now, u.id))
                    status = "re-allowed"
                else:
                    status = "unchanged"
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            u = _user(c.execute(f"SELECT {_USER_COLS} FROM users WHERE email=?", (e,)).fetchone())
        finally:
            c.close()
        return u, status

    def disallow(self, email: str) -> tuple[User, int]:
        """Refuse this email from now on and sign it out everywhere. Its data is kept."""
        u = self.user_by_email(email)
        if u is None:
            raise AccountError(f"{email} is not on the list; nothing changed.")
        self._x("UPDATE users SET allowed=0, changed_at=? WHERE id=?", (iso(self.now()), u.id))
        n = self.revoke_all(u.id, reason="account disallowed")
        return u, n

    def bind_google_sub(self, user: User, sub: str) -> bool:
        """First sign-in binds Google's account id to the email; later sign-ins must match."""
        if user.google_sub:
            return secrets.compare_digest(user.google_sub, sub)
        self._x("UPDATE users SET google_sub=?, changed_at=? WHERE id=? AND google_sub IS NULL",
                (sub, iso(self.now()), user.id))
        again = self.user_by_id(user.id)
        return again is not None and again.google_sub == sub

    # ---- where each account's data lives ---------------------------------------------
    @staticmethod
    def user_dir(settings, user: User) -> Path | None:
        """None = DATA_DIR itself (the --existing-data account)."""
        return None if user.existing_data else settings.users_dir / user.id

    def settings_for(self, settings, user: User):
        return settings.for_user(self.user_dir(settings, user))

    @staticmethod
    def prepare(user_settings) -> None:
        """Create a new account's folders and empty database (never touches DATA_DIR's own)."""
        if user_settings.is_main_data:
            return
        for d in (user_settings.root, user_settings.backups_dir, user_settings.import_dir,
                  user_settings.root / "modules"):
            d.mkdir(parents=True, exist_ok=True)
        db.init_db(user_settings.db_path)

    def other_user_settings(self, settings) -> list:
        """Settings of every allowed account that has its own folder (for snapshots)."""
        return [self.settings_for(settings, u) for u in self.users()
                if u.allowed and not u.existing_data]

    # ---- sessions ----------------------------------------------------------------------
    def new_session(self, user: User, method: str, ip: str | None, ua: str | None) -> str:
        token = secrets.token_urlsafe(32)
        now = self.now()
        self._x("INSERT INTO sessions(public_id, token_sha256, user_id, method, created, "
                "expires, last_seen, client_ip, user_agent) VALUES (?,?,?,?,?,?,?,?,?)",
                (secrets.token_hex(8), token_hash(token), user.id, method, now,
                 now + SESSION_SECONDS, now, ip, (ua or "")[:300]))
        return token

    def _session_rows(self, where: str, args) -> list[Session]:
        rows = self._q(
            "SELECT s.public_id, s.method, s.created, s.expires, s.last_seen, s.client_ip, "
            f"s.user_agent, u.{', u.'.join(_USER_COLS.split(', '))} FROM sessions s "
            f"JOIN users u ON u.id = s.user_id WHERE {where} ORDER BY s.created DESC", args)
        return [Session(public_id=r[0], method=r[1], created=r[2], expires=r[3], last_seen=r[4],
                        client_ip=r[5], user_agent=r[6], user=_user(r[7:])) for r in rows]

    def session(self, token: str | None, ip: str | None = None) -> Session | None:
        """The valid session for this cookie value, or None: unknown, revoked, expired (7 days
        after it was created), or the account is no longer allowed."""
        if not token or len(token) > 200:
            return None
        now = self.now()
        found = self._session_rows("s.token_sha256=? AND s.revoked IS NULL AND s.expires>? "
                                   "AND u.allowed=1", (token_hash(token), now))
        if not found:
            return None
        s = found[0]
        with self._lock:
            due = now - self._seen.get(s.public_id, 0) >= LAST_SEEN_EVERY
            if due:
                self._seen[s.public_id] = now
        if due:
            self._x("UPDATE sessions SET last_seen=?, client_ip=COALESCE(?, client_ip) "
                    "WHERE public_id=?", (now, ip, s.public_id))
        return s

    def active_sessions(self, user_id: str | None = None) -> list[Session]:
        now = self.now()
        if user_id is None:
            return self._session_rows("s.revoked IS NULL AND s.expires>?", (now,))
        return self._session_rows("s.revoked IS NULL AND s.expires>? AND s.user_id=?",
                                  (now, user_id))

    def revoke_token(self, token: str | None, reason: str = "signed out") -> bool:
        if not token or len(token) > 200:
            return False
        return self._x("UPDATE sessions SET revoked=?, revoked_reason=? WHERE token_sha256=? "
                       "AND revoked IS NULL", (self.now(), reason, token_hash(token))) > 0

    def revoke_one(self, user_id: str, public_id: str, reason: str = "signed out") -> bool:
        return self._x("UPDATE sessions SET revoked=?, revoked_reason=? WHERE public_id=? AND "
                       "user_id=? AND revoked IS NULL",
                       (self.now(), reason, public_id, user_id)) > 0

    def revoke_others(self, user_id: str, keep_public_id: str) -> int:
        return self._x("UPDATE sessions SET revoked=?, revoked_reason='signed out (others)' "
                       "WHERE user_id=? AND public_id<>? AND revoked IS NULL",
                       (self.now(), user_id, keep_public_id))

    def revoke_all(self, user_id: str | None = None, reason: str = "signed out (all)",
                   method: str | None = None) -> int:
        sql = "UPDATE sessions SET revoked=?, revoked_reason=? WHERE revoked IS NULL"
        args: list = [self.now(), reason]
        if user_id is not None:
            sql += " AND user_id=?"
            args.append(user_id)
        if method is not None:
            sql += " AND method=?"
            args.append(method)
        return self._x(sql, args)

    # ---- events ------------------------------------------------------------------------
    def event(self, event: str, method: str | None, email: str | None = None,
              user_id: str | None = None, reason: str | None = None, ip: str | None = None,
              ua: str | None = None) -> None:
        self._x("INSERT INTO sign_in_events(at, event, method, email, user_id, reason, "
                "client_ip, user_agent) VALUES (?,?,?,?,?,?,?,?)",
                (self.now(), event, method, (email or None) and email.lower()[:320], user_id,
                 (reason or None) and reason[:300], ip, (ua or "")[:300] or None))

    def events(self, user: User | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        cols = "at, event, method, email, reason, client_ip, user_agent"
        if user is None:
            rows = self._q(f"SELECT {cols} FROM sign_in_events ORDER BY id DESC LIMIT ?", (limit,))
        else:
            rows = self._q(f"SELECT {cols} FROM sign_in_events WHERE user_id=? OR email=? "
                           "ORDER BY id DESC LIMIT ?", (user.id, user.email, limit))
        return [{"at": iso(r[0]), "event": r[1], "method": r[2], "email": r[3], "reason": r[4],
                 "client_ip": r[5], "user_agent": r[6] or "", "device": device_label(r[6])}
                for r in rows]


# ---- CLI --------------------------------------------------------------------------------
def settings_for_email(settings, email: str | None):
    """The settings for --user <email> in the CLI tools. None/empty = DATA_DIR itself
    (Elisha's existing data), exactly as before Phase 9."""
    if not email:
        return settings
    if not settings.accounts_db.is_file():
        raise AccountError(f"No accounts yet ({settings.accounts_db}); "
                           "add one with: python -m server.accounts allow <email>")
    acc = Accounts(settings.accounts_db)
    u = acc.user_by_email(email)
    if u is None:
        raise AccountError(f"{email} is not an account (python -m server.accounts list).")
    us = acc.settings_for(settings, u)
    Accounts.prepare(us)
    return us


def main(argv=None) -> int:
    from .settings import SettingsError, load_settings
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="python -m server.accounts",
                                 description="Who may sign in to Drill (Phase 9).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("allow", help="approve an email (new accounts get their own database)")
    a.add_argument("email")
    a.add_argument("--existing-data", action="store_true",
                   help="this account uses DATA_DIR's existing drill.db, modules and backups "
                        "(one account only)")
    d = sub.add_parser("disallow", help="refuse an email and sign it out (its data is kept)")
    d.add_argument("email")
    sub.add_parser("list", help="list accounts")
    s = sub.add_parser("sessions", help="list active sessions")
    s.add_argument("--email")
    r = sub.add_parser("revoke-all", help="sign out every session (or one account's)")
    r.add_argument("--email")
    e = sub.add_parser("events", help="recent sign-in events")
    e.add_argument("--email")
    e.add_argument("--limit", type=int, default=30)
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as err:
        print(f"Stopped: {err}")
        return 2
    acc = Accounts(settings.accounts_db)
    try:
        if args.cmd == "allow":
            u, status = acc.allow(args.email, existing_data=args.existing_data)
            us = acc.settings_for(settings, u)
            Accounts.prepare(us)
            where = (f"{settings.data_dir} (the existing data, used in place)" if u.existing_data
                     else str(us.root))
            print(f"{u.email}: {status}. Data: {where}")
            if settings.auth_mode != "google":
                print("Note: AUTH_MODE is off in .env, so sign-in is not required yet.")
            return 0
        if args.cmd == "disallow":
            u, n = acc.disallow(args.email)
            acc.event("signed_out", "cli", u.email, u.id, f"account disallowed; {n} session(s)")
            print(f"{u.email}: disallowed, {n} session(s) signed out. Its data is kept.")
            return 0
        if args.cmd == "list":
            users = acc.users()
            if not users:
                print("No accounts. Add one: python -m server.accounts allow <email> "
                      "[--existing-data]")
            for u in users:
                n = len(acc.active_sessions(u.id))
                where = "DATA_DIR (existing data)" if u.existing_data else f"users/{u.id}"
                print(f"{u.email:<36} {'allowed' if u.allowed else 'NOT allowed':<12} "
                      f"{where:<28} sessions: {n}")
            return 0
        if args.cmd == "sessions":
            uid = None
            if args.email:
                u = acc.user_by_email(args.email)
                if u is None:
                    raise AccountError(f"{args.email} is not an account.")
                uid = u.id
            ss = acc.active_sessions(uid)
            print(f"Active sessions: {len(ss)}")
            for x in ss:
                print(f"  {x.user.email:<32} {x.method:<6} since {iso(x.created)}  last seen "
                      f"{iso(x.last_seen)}  from {x.client_ip}  {device_label(x.user_agent)}  "
                      f"(expires {iso(x.expires)})")
            return 0
        if args.cmd == "revoke-all":
            uid, who = None, "everyone"
            if args.email:
                u = acc.user_by_email(args.email)
                if u is None:
                    raise AccountError(f"{args.email} is not an account.")
                uid, who = u.id, u.email
            n = acc.revoke_all(uid, reason="revoke-all (PC)")
            acc.event("signed_out", "cli", None if uid is None else who, uid,
                      f"revoke-all: {n} session(s)")
            print(f"Signed out {n} session(s) ({who}).")
            return 0
        if args.cmd == "events":
            u = acc.user_by_email(args.email) if args.email else None
            if args.email and u is None:
                raise AccountError(f"{args.email} is not an account.")
            for ev in acc.events(u, args.limit):
                print(f"{ev['at']}  {ev['event']:<10} {ev['method'] or '':<6} "
                      f"{ev['email'] or '-':<32} {ev['reason'] or '':<30} {ev['client_ip'] or ''}"
                      f"  {ev['device']}")
            return 0
    except AccountError as err:
        print(f"Not done: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
