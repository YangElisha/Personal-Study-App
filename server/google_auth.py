"""Phase 9: "Sign in with Google" (OpenID Connect, authorization code flow + PKCE), stdlib only.

  GET /auth/google/start     -> 302 to Google (state, nonce, PKCE S256, prompt=select_account)
  GET /auth/google/callback  -> code exchanged at https://oauth2.googleapis.com/token over TLS
                                (certificate checked by Python's default SSL context)

The id_token comes straight from Google's token endpoint over that verified TLS connection,
so its signature is not checked separately (OpenID Connect Core 3.1.3.7, item 6); its claims
are: iss, aud (== our client id; azp too when aud has several), exp and iat (60 s skew),
nonce (== the one we sent), email_verified true. Nothing here needs the internet except the
sign-in itself: sessions are checked locally, so the app keeps working offline.

The state, nonce and PKCE verifier live server-side (in memory, 10 minutes, one use), bound
to the browser that started the sign-in by a short-lived HttpOnly cookie, so a sign-in link
made by someone else cannot sign this browser in to their account.
The client secret is only sent in the token request body; it is never logged or shown.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("drill.auth")

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
START_PATH = "/auth/google/start"
CALLBACK_PATH = "/auth/google/callback"
SIGNIN_PATH = "/auth/signin"
FLOW_COOKIE = "drill_oauth"
FLOW_SECONDS = 600
SKEW = 60
REDIRECT_HOSTS = ("localhost", "127.0.0.1")   # the two redirect URIs registered with Google

# rate limits, per client IP (in memory; a restart clears them)
CALLBACK_MAX, CALLBACK_WINDOW = 20, 600        # callback requests per 10 minutes
FAIL_MAX, LOCK_SECONDS = 10, 15 * 60           # failed sign-ins before a 15-minute lock


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str = field(repr=False)
    auth_endpoint: str = AUTH_ENDPOINT
    token_endpoint: str = TOKEN_ENDPOINT
    reach_host: str | None = "accounts.google.com:443"   # None: skip the "online?" check
    timeout: float = 15.0


class SignInError(Exception):
    """code: what the sign-in page says (see MESSAGES); reason: what the log says."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


MESSAGES = {
    "not_approved": "That Google account is not approved for Drill. Choose another account, "
                    "or ask for this one to be added.",
    "account_mismatch": "This email is approved, but for a different Google account. "
                        "Nothing was opened.",
    "offline": "Can't reach Google. Signing in needs the internet; once you are signed in, "
               "Drill keeps working offline for 7 days.",
    "expired": "Your sign-in has ended (sign-ins last 7 days, or it was signed out). "
               "Sign in again.",
    "retry": "That sign-in attempt expired or was already used. Please try again.",
    "cancelled": "Sign-in was cancelled.",
    "failed": "Google sign-in did not complete. Please try again.",
    "rate_limited": "Too many sign-in attempts from this device. Wait 15 minutes and try again.",
    "signed_out": "You are signed out.",
    "wrong_host": "",   # filled in with the address to use
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)                    # 86 characters (43..128 allowed)
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


@dataclass
class Flow:
    verifier: str
    nonce: str
    browser_hash: str
    redirect_uri: str
    created: float


class PendingFlows:
    """Sign-ins in progress: state -> Flow. One use, 10 minutes, at most 200 at a time."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._flows: dict[str, Flow] = {}
        self._lock = threading.Lock()

    def start(self, redirect_uri: str) -> tuple[str, str, Flow, str]:
        """Returns (state, browser cookie value, flow, code_challenge)."""
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        flow = Flow(verifier=verifier, nonce=secrets.token_urlsafe(32),
                    browser_hash=hashlib.sha256(browser.encode()).hexdigest(),
                    redirect_uri=redirect_uri, created=self.clock())
        with self._lock:
            now = self.clock()
            for k in [k for k, f in self._flows.items() if now - f.created > FLOW_SECONDS]:
                del self._flows[k]
            while len(self._flows) >= 200:
                del self._flows[next(iter(self._flows))]
            self._flows[state] = flow
        return state, browser, flow, challenge

    def take(self, state: str | None, browser: str | None) -> Flow:
        """The flow for this state (removed: one use). Raises SignInError('retry')."""
        with self._lock:
            flow = self._flows.pop(state, None) if state else None
        if flow is None:
            raise SignInError("retry", "unknown or already used state")
        if self.clock() - flow.created > FLOW_SECONDS:
            raise SignInError("retry", "sign-in attempt older than 10 minutes")
        got = hashlib.sha256((browser or "").encode()).hexdigest()
        if not browser or not secrets.compare_digest(got, flow.browser_hash):
            raise SignInError("retry", "state was not started by this browser")
        return flow


def authorize_url(cfg: GoogleConfig, redirect_uri: str, state: str, nonce: str,
                  challenge: str) -> str:
    q = urllib.parse.urlencode({
        "client_id": cfg.client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account"})
    return f"{cfg.auth_endpoint}?{q}"


def reachable(host_port: str | None, timeout: float = 3.0) -> bool:
    if not host_port:
        return True
    host, _, port = host_port.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def exchange_code(cfg: GoogleConfig, code: str, verifier: str, redirect_uri: str) -> dict:
    """POST the code to Google's token endpoint. Returns its JSON. Raises SignInError."""
    body = urllib.parse.urlencode({
        "code": code, "client_id": cfg.client_id, "client_secret": cfg.client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        "code_verifier": verifier}).encode("ascii")
    req = urllib.request.Request(cfg.token_endpoint, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    ctx = ssl.create_default_context()          # verifies Google's certificate and host name
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout, context=ctx) as r:
            return json.loads(r.read(1 << 20).decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read(4096).decode("utf-8")).get("error", "")
        except (ValueError, AttributeError, OSError):
            err = ""
        raise SignInError("failed", f"token endpoint answered {e.code} {err}".strip()) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as e:
        raise SignInError("offline", f"token endpoint unreachable ({type(e).__name__})") from None
    except ValueError:
        raise SignInError("failed", "token endpoint answered something that is not JSON") from None


def id_token_claims(id_token: str) -> dict:
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        raise SignInError("failed", "id_token is not a JWT")
    try:
        claims = json.loads(b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SignInError("failed", "id_token payload unreadable") from None
    if not isinstance(claims, dict):
        raise SignInError("failed", "id_token payload is not an object")
    return claims


def validate_claims(claims: dict, client_id: str, nonce: str, now: float) -> tuple[str, str]:
    """Returns (email lower-cased, sub). Raises SignInError('failed', why)."""
    def fail(why):
        raise SignInError("failed", why)
    if claims.get("iss") not in ISSUERS:
        fail(f"wrong issuer {str(claims.get('iss'))[:80]!r}")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if client_id not in auds:
        fail("audience is not this app's client id")
    if (len(auds) > 1 or "azp" in claims) and claims.get("azp") != client_id:
        fail("azp is not this app")
    try:
        exp, iat = float(claims["exp"]), float(claims["iat"])
    except (KeyError, TypeError, ValueError):
        fail("exp/iat missing")
    if exp < now - SKEW:
        fail("id_token expired")
    if iat > now + SKEW:
        fail("id_token issued in the future")
    got = claims.get("nonce")
    if not isinstance(got, str) or not secrets.compare_digest(got, nonce):
        fail("nonce mismatch")
    if claims.get("email_verified") not in (True, "true"):
        fail("email not verified by Google")
    email, sub = claims.get("email"), claims.get("sub")
    if not isinstance(email, str) or "@" not in email or not isinstance(sub, str) or not sub:
        fail("email or sub missing")
    return email.strip().lower(), sub


class RateLimit:
    """Per-IP: callback requests in a sliding window, and failed sign-ins -> 15-minute lock."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._hits: dict[str, list[float]] = {}
        self._fails: dict[str, list] = {}          # ip -> [count, locked_until]
        self._lock = threading.Lock()

    def locked(self, ip: str) -> bool:
        with self._lock:
            f = self._fails.get(ip)
            if not f or not f[1]:
                return False
            if f[1] <= self.clock():
                self._fails.pop(ip, None)
                return False
            return True

    def hit(self, ip: str) -> bool:
        """Count one callback request. False = over the limit."""
        with self._lock:
            now = self.clock()
            hits = [t for t in self._hits.get(ip, []) if now - t < CALLBACK_WINDOW]
            hits.append(now)
            self._hits[ip] = hits
            return len(hits) <= CALLBACK_MAX

    def fail(self, ip: str) -> bool:
        """Count one failed sign-in. True = this locked the IP."""
        with self._lock:
            f = self._fails.setdefault(ip, [0, 0.0])
            f[0] += 1
            if f[0] >= FAIL_MAX and not f[1]:
                f[1] = self.clock() + LOCK_SECONDS
                return True
            return False

    def success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


# ---- the sign-in page (inline, no external files: works offline) --------------------------
G_MARK = ('<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">'
          '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 '
          '24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
          '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 '
          '2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
          '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98'
          '-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
          '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 '
          '2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
          '</svg>')

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Sign in - Drill</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f4f1ea;color:#222}
main{width:100%;max-width:25rem;padding:1.5rem}
h1{font-size:1.7rem;margin:0 0 .3rem}
p{line-height:1.5;margin:.6rem 0}
.gbtn{display:flex;align-items:center;justify-content:center;gap:.75rem;width:100%;
margin:1.2rem 0 1rem;padding:.8rem 1rem;min-height:48px;border:1px solid #747775;
border-radius:.35rem;background:#fff;color:#1f1f1f;font:500 1rem/1.2 "Segoe UI",Roboto,
Arial,sans-serif;text-decoration:none}
.gbtn:hover{background:#f7f8f8}.gbtn:focus{outline:3px solid #2f5d8a;outline-offset:2px}
.gbtn[aria-disabled=true]{opacity:.45;pointer-events:none}
.msg{padding:.7rem .9rem;border-radius:.4rem;background:#fbe9e7;color:#8a1c12;font-weight:600}
.msg.info{background:#e8eef5;color:#1e3f60}
.small{font-size:.9rem;color:#555}
@media (prefers-color-scheme:dark){body{background:#1c1c1e;color:#eee}.small{color:#aaa}
.msg{background:#4a1f1a;color:#ffd7d0}.msg.info{background:#1f3144;color:#d6e6f7}}
</style></head><body><main>
<h1>Drill</h1>
{MSG}
<p id="offline" class="msg" role="alert" hidden>You're offline. Signing in needs the internet.</p>
<a class="gbtn" id="go" href="/auth/google/start">{GMARK}<span>Sign in with Google</span></a>
<p class="small">Only approved Google accounts can sign in. If your Google account uses
2-Step Verification, Google asks for your one-time code (from your phone or authenticator
app) on Google's own page; Drill never sees your password or codes.</p>
<p class="small">A sign-in lasts 7 days and keeps working offline. Signing in again needs the
internet.</p>
</main>
<script>
(function(){var o=document.getElementById("offline"),g=document.getElementById("go");
function u(){var off=navigator.onLine===false;o.hidden=!off;g.setAttribute("aria-disabled",off?"true":"false");}
addEventListener("online",u);addEventListener("offline",u);u();})();
</script></body></html>"""


def signin_page(code: str = "", port: int | str = "") -> str:
    if code == "wrong_host":
        text = (f"Open Drill at http://localhost:{port}/ to sign in "
                "(Google only accepts that address).")
    else:
        text = MESSAGES.get(code, "")
    cls = "msg info" if code == "signed_out" else "msg"
    msg = f'<p class="{cls}" role="alert">{html.escape(text)}</p>' if text else ""
    return _PAGE.replace("{MSG}", msg).replace("{GMARK}", G_MARK)


def continue_page() -> str:
    """Shown after a successful callback. Its meta refresh is a new, same-site navigation, so
    the SameSite=Strict session cookie is sent with it (a 303 from the callback would still
    count as part of the cross-site navigation that came from Google, and Strict cookies are
    not sent on that)."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0;url=/"><meta name="referrer" '
            'content="no-referrer"><title>Drill</title></head><body style="font-family:'
            'system-ui,sans-serif;padding:2rem">Signed in. <a href="/">Open Drill</a></body>'
            '</html>')
