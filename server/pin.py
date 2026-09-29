"""Phone-access PIN (Phase 8).

  python -m server.pin set [--email <email>]
                                    set or change the PIN (asks twice; 6+ digits).
                                    Changing it signs every phone out. With AUTH_MODE=google
                                    --email is required: PIN sessions act as that account.
  python -m server.pin revoke-all   sign every phone out now (the PIN stays)
  python -m server.pin status       is a PIN set, how many phones are signed in

Stored in DATA_DIR\\phone-access.db as a salted scrypt hash. Works while the server runs.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .accounts import Accounts, iso
from .phone import MIN_PIN_DIGITS, PhoneAuth, valid_pin_format
from .settings import SettingsError, load_settings


def main(argv=None, ask=getpass.getpass) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.pin")
    ap.add_argument("action", choices=["set", "revoke-all", "status"])
    ap.add_argument("--email", help="the account this PIN signs in as (AUTH_MODE=google)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as e:
        print(f"Not done: {e}")
        return 2
    auth = PhoneAuth(settings.phone_db)
    google = settings.auth_mode == "google"
    acc = Accounts(settings.accounts_db) if google or settings.accounts_db.is_file() else None

    if args.action == "set":
        email = None
        if args.email:
            u = acc.user_by_email(args.email) if acc else None
            if u is None or not u.allowed:
                print(f"Not set: {args.email} is not an approved account "
                      "(python -m server.accounts allow <email>).")
                return 1
            email = u.email
        elif google:
            print("Not set: with AUTH_MODE=google a PIN belongs to one account. "
                  "Run: python -m server.pin set --email <email>")
            return 1
        first = ask(f"New PIN ({MIN_PIN_DIGITS}+ digits): ").strip()
        if not valid_pin_format(first):
            print(f"Not set: the PIN must be at least {MIN_PIN_DIGITS} digits, digits only.")
            return 1
        if ask("Same PIN again: ").strip() != first:
            print("Not set: the two PINs were different.")
            return 1
        n = auth.set_pin(first, email)
        if acc is not None:
            n += acc.revoke_all(reason="PIN changed", method="pin")
        who = f" for {email}" if email else ""
        print(f"PIN set{who}. {n} phone session(s) signed out." if n else f"PIN set{who}.")
        return 0

    if args.action == "revoke-all":
        n = auth.revoke_all()
        if acc is not None:
            n += acc.revoke_all(reason="PIN revoke-all", method="pin")
        print(f"Signed out {n} phone session(s).")
        return 0

    sessions = auth.active_sessions()
    email = auth.pin_email()
    print(f"PIN: {'set' if auth.pin_is_set() else 'NOT set'}"
          + (f" (signs in as {email})" if email else ""))
    if acc is not None:
        for x in acc.active_sessions():
            if x.method == "pin":
                sessions.append((iso(x.created), iso(x.expires), x.client_ip,
                                 x.user_agent or "", None))
    print(f"Signed-in phones: {len(sessions)}")
    for created, expires, ip, ua, _seen in sessions:
        print(f"  since {created} from {ip}  (expires {expires[:10]})  {ua[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
