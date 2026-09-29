"""Phone-access PIN (Phase 8).

  python -m server.pin set          set or change the PIN (asks twice; 6+ digits).
                                    Changing it signs every phone out.
  python -m server.pin revoke-all   sign every phone out now (the PIN stays)
  python -m server.pin status       is a PIN set, how many phones are signed in

Stored in DATA_DIR\\phone-access.db as a salted scrypt hash. Works while the server runs.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .phone import MIN_PIN_DIGITS, PhoneAuth, valid_pin_format
from .settings import SettingsError, load_settings


def main(argv=None, ask=getpass.getpass) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.pin")
    ap.add_argument("action", choices=["set", "revoke-all", "status"])
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as e:
        print(f"Not done: {e}")
        return 2
    auth = PhoneAuth(settings.phone_db)

    if args.action == "set":
        first = ask(f"New PIN ({MIN_PIN_DIGITS}+ digits): ").strip()
        if not valid_pin_format(first):
            print(f"Not set: the PIN must be at least {MIN_PIN_DIGITS} digits, digits only.")
            return 1
        if ask("Same PIN again: ").strip() != first:
            print("Not set: the two PINs were different.")
            return 1
        n = auth.set_pin(first)
        print(f"PIN set. {n} phone session(s) signed out." if n else "PIN set.")
        return 0

    if args.action == "revoke-all":
        n = auth.revoke_all()
        print(f"Signed out {n} phone session(s).")
        return 0

    sessions = auth.active_sessions()
    print(f"PIN: {'set' if auth.pin_is_set() else 'NOT set'}")
    print(f"Signed-in phones: {len(sessions)}")
    for created, expires, ip, ua, _seen in sessions:
        print(f"  since {created} from {ip}  (expires {expires[:10]})  {ua[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
