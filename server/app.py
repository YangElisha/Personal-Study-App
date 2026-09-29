"""The FastAPI application. Contract: docs/API.md."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import accounts as acc_mod
from . import ai, db, google_auth, modules, phone, snapshots
from .settings import REPO_ROOT, Settings

log = logging.getLogger("drill")

# Windows' registry often maps .woff2 to application/octet-stream (or nothing); fonts are
# vendored in app/vendor/fonts, so give them their proper types.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

ALLOWED_HOSTS = phone.LOCAL_HOSTS   # plus Tailscale names when PHONE_ACCESS=on

# Security headers on every response (Phase 9). The app is one HTML file with inline script
# and style; pdf.js runs in a worker from vendor/; page images are data:/blob: URLs.
# pdf.js 3.x probes eval support with new Function(""); blocked here, it uses its non-eval path.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; "
       "worker-src 'self' blob:; font-src 'self'; frame-ancestors 'none'; object-src 'none'; "
       "base-uri 'none'; form-action 'self' https://accounts.google.com")
SECURITY_HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}

PLACEHOLDER = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Drill</title></head><body style="font-family:system-ui,sans-serif;max-width:40em;
margin:4em auto;line-height:1.5"><h1>Drill server is running</h1>
<p>The app itself (<code>app/index.html</code>) is added in Phase 4. Until then this page is
all there is to see here. Your data is safe in the database.</p>
<p><a href="/api/health">/api/health</a></p></body></html>"""


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def _err(status: int, kind: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": False, "error": kind, "message": message, **extra}, status_code=status)


def create_app(settings: Settings, app_dir: Path | None = None,
               daily_check_seconds: float = 600.0,
               ai_config: "ai.AIConfig | None" = None,
               modules_md_paths: "list[Path] | None" = None,
               detect_tailscale: bool = True,
               google_config: "google_auth.GoogleConfig | None" = None,
               google_exchange=None, clock=None) -> FastAPI:
    """google_config, google_exchange, clock: for tests (a fake Google, a fake clock)."""
    app_dir = REPO_ROOT / "app" if app_dir is None else app_dir
    md_paths = (modules.default_md_paths(settings) if modules_md_paths is None
                else modules_md_paths)
    clock = clock or time.time
    google_mode = settings.auth_mode == "google"
    accounts = acc_mod.Accounts(settings.accounts_db, clock=clock) if google_mode else None
    gcfg = google_config or google_auth.GoogleConfig(settings.google_client_id,
                                                     settings.google_client_secret)
    exchange = google_exchange or google_auth.exchange_code
    flows = google_auth.PendingFlows(clock=clock)
    limiter = google_auth.RateLimit()
    prepared: set = set()

    def md_for(us: Settings):
        # Elisha's data keeps the repo's MODULES.md; other accounts only their own copy
        return md_paths if us.is_main_data else modules.default_md_paths(us)

    def snapshot_targets() -> list:
        """drill.db in DATA_DIR (always, as before) + every other approved account's own."""
        out = [settings]
        if accounts is not None:
            out += [us for us in accounts.other_user_settings(settings) if us.db_path.exists()]
        return out

    async def daily_snapshots():
        while True:
            await asyncio.sleep(daily_check_seconds)
            try:
                targets = await asyncio.to_thread(snapshot_targets)
            except Exception:
                log.exception("listing accounts for snapshots failed")
                targets = [settings]
            for us in targets:
                try:
                    if snapshots.daily_due(us):
                        p = await asyncio.to_thread(snapshots.take_snapshot, us)
                        log.info("daily snapshot %s", p)
                except Exception:                   # never let the loop die
                    log.exception("daily snapshot failed (%s)", us.root)

    @asynccontextmanager
    async def lifespan(_app):
        db.init_db(settings.db_path)
        p = snapshots.take_snapshot(settings)
        log.info("snapshot on start: %s", p)
        for us in snapshot_targets()[1:]:
            try:
                log.info("snapshot on start: %s", snapshots.take_snapshot(us))
            except Exception:
                log.exception("snapshot on start failed (%s)", us.root)
        task = asyncio.create_task(daily_snapshots())
        try:
            yield
        finally:
            task.cancel()
            try:
                targets = snapshot_targets()
            except Exception:
                targets = [settings]
            for us in targets:
                try:
                    db.checkpoint(us.db_path)
                except Exception:
                    log.exception("checkpoint on shutdown failed (%s)", us.root)

    app = FastAPI(title="Drill local server", lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.accounts = accounts

    # ---- access guard (Phase 8 adds phone access; see server/phone.py) ----------------
    hosts = phone.HostList(settings.phone_access, settings.phone_allow_lan,
                           tuple(settings.phone_hosts), detect=detect_tailscale)
    hosts.refresh()
    auth = phone.PhoneAuth(settings.phone_db)
    app.state.phone_hosts, app.state.phone_auth = hosts, auth
    safe_methods = ("GET", "HEAD", "OPTIONS")

    def html(text: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(text, status_code=status,
                            headers={"X-Frame-Options": "DENY", "Cache-Control": "no-store"})

    async def phone_login(request: Request, ip: str):
        left = auth.locked_for(ip)
        if left:
            return html(phone.login_page(
                f"Too many wrong PINs. Locked for {(left + 59) // 60} more minute(s).",
                locked=True), 429)
        if not await asyncio.to_thread(auth.pin_is_set):
            return html(phone.no_pin_page(), 403)
        raw = (await request.body())[:4096].decode("utf-8", "replace")
        pin = ""
        if raw.lstrip().startswith("{"):
            try:
                v = json.loads(raw).get("pin")
                pin = v if isinstance(v, str) else ""
            except (ValueError, AttributeError):
                pin = ""
        else:
            pin = (parse_qs(raw).get("pin") or [""])[0]
        pin = pin.strip()
        if phone.valid_pin_format(pin) and await asyncio.to_thread(auth.check_pin, pin):
            auth.clear_failures(ip)
            token = await asyncio.to_thread(auth.new_session, ip,
                                            request.headers.get("user-agent"))
            await asyncio.to_thread(auth.event, ip, "signed in")
            log.info("phone access: %s signed in", ip)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(phone.COOKIE, token, max_age=phone.SESSION_DAYS * 86400,
                            path="/", httponly=True, samesite="strict")
            return resp
        locked = await asyncio.to_thread(auth.record_failure, ip)
        if locked:
            return html(phone.login_page(
                "Too many wrong PINs. Locked for 15 minutes.", locked=True), 429)
        return html(phone.login_page("Wrong PIN."), 401)

    # ---- Phase 9: Google sign-in (AUTH_MODE=google). See server/google_auth.py -----------
    def user_settings_for(user) -> Settings:
        us = accounts.settings_for(settings, user)
        if not us.is_main_data and us.root not in prepared:
            acc_mod.Accounts.prepare(us)          # a new account's own folder + empty drill.db
            prepared.add(us.root)
        return us

    def signin(code: str = "", status: int = 200) -> HTMLResponse:
        return html(google_auth.signin_page(code, settings.port), status)

    def set_session_cookie(resp, token: str) -> None:
        resp.set_cookie(acc_mod.COOKIE, token, max_age=acc_mod.SESSION_SECONDS, path="/",
                        httponly=True, samesite="strict")

    def clear_session_cookie(resp) -> None:
        resp.delete_cookie(acc_mod.COOKIE, path="/", httponly=True, samesite="strict")

    async def google_start(ip: str, host: str):
        if limiter.locked(ip):
            return signin("rate_limited", 429)
        if host not in google_auth.REDIRECT_HOSTS:
            return signin("wrong_host", 400)
        if not await asyncio.to_thread(google_auth.reachable, gcfg.reach_host):
            return signin("offline", 503)
        redirect_uri = f"http://{host}:{settings.port}{google_auth.CALLBACK_PATH}"
        state, browser, flow, challenge = flows.start(redirect_uri)
        resp = RedirectResponse(google_auth.authorize_url(gcfg, redirect_uri, state, flow.nonce,
                                                          challenge), status_code=302)
        # Lax, not Strict: it has to come back with the top-level navigation from Google
        resp.set_cookie(google_auth.FLOW_COOKIE, browser, max_age=google_auth.FLOW_SECONDS,
                        path="/auth/google/", httponly=True, samesite="lax")
        return resp

    async def google_callback(request: Request, ip: str):
        ua = request.headers.get("user-agent")
        if limiter.locked(ip) or not limiter.hit(ip):
            log.warning("sign-in: %s rate-limited", ip)
            return signin("rate_limited", 429)
        q = request.query_params
        seen = {"email": None}

        def refuse(code: str, reason: str, status: int):
            reason = reason.replace("\r", " ").replace("\n", " ")
            locked = code not in ("offline", "cancelled") and limiter.fail(ip)
            log.warning("sign-in refused from %s: %s%s", ip, reason,
                        " (locked for 15 minutes)" if locked else "")
            accounts.event("refused", "google", seen["email"], None, reason, ip, ua)
            resp = signin("rate_limited" if locked else code, 429 if locked else status)
            resp.delete_cookie(google_auth.FLOW_COOKIE, path="/auth/google/")
            return resp

        try:
            flow = flows.take(q.get("state"), request.cookies.get(google_auth.FLOW_COOKIE))
        except google_auth.SignInError as e:
            return await asyncio.to_thread(refuse, e.code, e.reason, 400)
        if q.get("error"):
            code = "cancelled" if q.get("error") == "access_denied" else "failed"
            return await asyncio.to_thread(refuse, code, f"Google said {q.get('error')[:60]}", 400)
        if not q.get("code"):
            return await asyncio.to_thread(refuse, "failed", "no code in the callback", 400)
        try:
            tok = await asyncio.to_thread(exchange, gcfg, q.get("code"), flow.verifier,
                                          flow.redirect_uri)
            claims = google_auth.id_token_claims((tok or {}).get("id_token", "")
                                                 if isinstance(tok, dict) else "")
            if isinstance(claims.get("email"), str):
                seen["email"] = claims["email"][:320]
            email, sub = google_auth.validate_claims(claims, gcfg.client_id, flow.nonce,
                                                     clock())
        except google_auth.SignInError as e:
            return await asyncio.to_thread(refuse, e.code, e.reason,
                                           503 if e.code == "offline" else 400)
        user = await asyncio.to_thread(accounts.user_by_email, email)
        if user is None or not user.allowed:
            return await asyncio.to_thread(refuse, "not_approved", "email not approved", 403)
        if not await asyncio.to_thread(accounts.bind_google_sub, user, sub):
            return await asyncio.to_thread(refuse, "account_mismatch",
                                           "Google account id differs from the approved one", 403)
        await asyncio.to_thread(user_settings_for, user)
        token = await asyncio.to_thread(accounts.new_session, user, "google", ip, ua)
        await asyncio.to_thread(accounts.event, "signed_in", "google", user.email, user.id,
                                None, ip, ua)
        limiter.success(ip)
        log.info("signed in: %s from %s", user.email, ip)
        resp = html(google_auth.continue_page())
        set_session_cookie(resp, token)
        resp.delete_cookie(google_auth.FLOW_COOKIE, path="/auth/google/")
        return resp

    async def phone_login_google(request: Request, ip: str):
        """PIN sign-in from the phone when AUTH_MODE=google: the PIN belongs to one account."""
        ua = request.headers.get("user-agent")
        left = auth.locked_for(ip)
        if left:
            return html(phone.login_page(
                f"Too many wrong PINs. Locked for {(left + 59) // 60} more minute(s).",
                locked=True), 429)
        email = await asyncio.to_thread(auth.pin_email)
        user = await asyncio.to_thread(accounts.user_by_email, email) if email else None
        if not await asyncio.to_thread(auth.pin_is_set) or user is None or not user.allowed:
            return html(phone.no_pin_page(bound=True), 403)
        raw = (await request.body())[:4096].decode("utf-8", "replace")
        pin = ""
        if raw.lstrip().startswith("{"):
            try:
                v = json.loads(raw).get("pin")
                pin = v if isinstance(v, str) else ""
            except (ValueError, AttributeError):
                pin = ""
        else:
            pin = (parse_qs(raw).get("pin") or [""])[0]
        pin = pin.strip()
        if phone.valid_pin_format(pin) and await asyncio.to_thread(auth.check_pin, pin):
            auth.clear_failures(ip)
            await asyncio.to_thread(user_settings_for, user)
            token = await asyncio.to_thread(accounts.new_session, user, "pin", ip, ua)
            await asyncio.to_thread(accounts.event, "signed_in", "pin", user.email, user.id,
                                    None, ip, ua)
            log.info("phone access: %s signed in as %s", ip, user.email)
            resp = RedirectResponse("/", status_code=303)
            set_session_cookie(resp, token)
            return resp
        await asyncio.to_thread(accounts.event, "refused", "pin", None, None, "wrong PIN", ip, ua)
        locked = await asyncio.to_thread(auth.record_failure, ip)
        if locked:
            return html(phone.login_page(
                "Too many wrong PINs. Locked for 15 minutes.", locked=True), 429)
        return html(phone.login_page("Wrong PIN."), 401)

    async def google_guard(request: Request, call_next, ip, host: str):
        """AUTH_MODE=google: every request needs a valid session, this PC included."""
        path, method, ips = request.url.path, request.method, str(ip)
        local = phone.is_local(ip)
        token = request.cookies.get(acc_mod.COOKIE)
        if path.startswith("/auth/"):
            if not local:              # Google only redirects back to this PC's own names
                return RedirectResponse("/", status_code=303)
            if method in ("GET", "HEAD"):
                if path == google_auth.START_PATH:
                    return await google_start(ips, host)
                if path == google_auth.CALLBACK_PATH:
                    return await google_callback(request, ips)
                if path == google_auth.SIGNIN_PATH:
                    code = request.query_params.get("error", "")
                    return signin(code if code in google_auth.MESSAGES else "")
            return _err(404, "not_found", "Not found")
        if not local and method == "POST" and path == phone.LOGIN_PATH:
            return await phone_login_google(request, ips)
        if not local and method == "POST" and path == phone.LOGOUT_PATH:
            await asyncio.to_thread(accounts.revoke_token, token)
            resp = RedirectResponse("/", status_code=303)
            clear_session_cookie(resp)
            return resp
        sess = await asyncio.to_thread(accounts.session, token, ips)
        if sess is None:
            if path.startswith("/api/") or method not in ("GET", "HEAD"):
                resp = _err(401, "auth_required", "Sign in first",
                            sign_in="google" if local else "pin")
            elif not local:
                if not await asyncio.to_thread(auth.pin_is_set) or \
                        not await asyncio.to_thread(auth.pin_email):
                    resp = html(phone.no_pin_page(bound=True), 403)
                elif path != "/":
                    resp = RedirectResponse("/", status_code=303)
                else:
                    resp = html(phone.login_page())
            elif path != "/":
                resp = RedirectResponse("/", status_code=303)
            else:
                resp = signin("expired" if token else "")
                if token:
                    clear_session_cookie(resp)     # unknown, expired or revoked: forget it
            return resp
        request.state.session = sess
        request.state.user_settings = await asyncio.to_thread(user_settings_for, sess.user)
        return await call_next(request)

    @app.middleware("http")
    async def harden(request: Request, call_next):
        try:
            resp = await guard(request, call_next)
        except Exception:            # an unhandled error still gets the security headers
            log.exception("unhandled error on %s", request.url.path)
            resp = _err(500, "server_error", "Internal error")
        for k, v in SECURITY_HEADERS.items():
            resp.headers[k] = v
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/auth/"):
            resp.headers["Cache-Control"] = "no-store"      # data: never from a cache
        elif "cache-control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-cache"      # app files: revalidate
        return resp

    async def guard(request: Request, call_next):
        request.state.session = None
        request.state.user_settings = settings
        # 1. Who is asking. Off: this PC only. On: this PC, Tailscale, (LAN if allowed).
        #    Everyone else is refused before anything else happens.
        ip = phone.client_ip(request.client.host if request.client else None)
        if not phone.client_allowed(ip, settings.phone_access, settings.phone_allow_lan):
            return _err(403, "forbidden_client", "This device is not allowed to use Drill")
        # 2. DNS-rebinding guard: only answer requests addressed to this PC by a known name.
        host, port = phone.split_host(request.headers.get("host") or "")
        if host not in hosts.allowed() and hosts.stale():
            await asyncio.to_thread(hosts.refresh)   # Tailscale may have started after us
        if host not in hosts.allowed():
            return _err(403, "forbidden_host", f"Host {request.headers.get('host')!r} is not allowed")
        # 3. Only the app's own page may change anything. A state-changing request that carries
        # an Origin header (browsers always send one on cross-site requests, and "null" from
        # sandboxed frames and file:// pages) must come from this server's own origin, built
        # from the Host the request was addressed to (the local names are interchangeable).
        # Requests with no Origin (curl, the CLI tools, same-origin navigation) are allowed.
        if request.method not in safe_methods:
            origin = request.headers.get("origin")
            if origin is not None:
                names = phone.LOCAL_HOSTS if host in phone.LOCAL_HOSTS else {host}
                own = {phone.origin_for(h, port) for h in names}
                if origin.strip().lower().rstrip("/") not in own:
                    return _err(403, "forbidden_origin", f"Origin {origin!r} may not write here")
        # 4. AUTH_MODE=google (Phase 9): a session for everyone, this PC included.
        if google_mode:
            return await google_guard(request, call_next, ip, host)
        # 4. AUTH_MODE=off: the PIN. Every client other than this PC needs a session.
        if not phone.is_local(ip):
            path, ips = request.url.path, str(ip)
            if path == phone.LOGIN_PATH and request.method == "POST":
                return await phone_login(request, ips)
            token = request.cookies.get(phone.COOKIE)
            if path == phone.LOGOUT_PATH and request.method == "POST":
                await asyncio.to_thread(auth.revoke, token)
                resp = RedirectResponse("/", status_code=303)
                resp.delete_cookie(phone.COOKIE, path="/", httponly=True, samesite="strict")
                return resp
            if not await asyncio.to_thread(auth.session_valid, token):
                api = path.startswith("/api/") or request.method not in ("GET", "HEAD")
                if not await asyncio.to_thread(auth.pin_is_set):
                    if api:
                        return _err(401, "pin_not_set", "Set a PIN on the PC first "
                                    "(python -m server.pin set)")
                    return html(phone.no_pin_page(), 403)
                if api:
                    return _err(401, "pin_required", "Sign in with the PIN first")
                if path != "/":
                    return RedirectResponse("/", status_code=303)
                return html(phone.login_page())
        return await call_next(request)

    def us_of(request: Request) -> Settings:
        """The signed-in account's data (DATA_DIR itself when AUTH_MODE=off)."""
        return getattr(request.state, "user_settings", None) or settings

    def conn(request: Request):
        return db.connect(us_of(request).db_path)

    # ---- account & security (Phase 9). Contract: docs/API.md "Sign-in" -----------------
    def need_session(request: Request):
        sess = getattr(request.state, "session", None)
        if not google_mode or sess is None:
            return None, _err(404, "auth_off", "Sign-in is off (AUTH_MODE=off)")
        return sess, None

    @app.get("/api/auth/me")
    def auth_me(request: Request):
        sess = getattr(request.state, "session", None)
        if not google_mode or sess is None:
            return {"ok": True, "auth_mode": settings.auth_mode, "user": None, "session": None}
        return {"ok": True, "auth_mode": "google", "user": sess.user.public(),
                "session": sess.public(sess.public_id)}

    @app.get("/api/auth/sessions")
    def auth_sessions(request: Request):
        sess, err = need_session(request)
        if err:
            return err
        return {"ok": True, "sessions": [s.public(sess.public_id)
                                         for s in accounts.active_sessions(sess.user.id)]}

    @app.get("/api/auth/events")
    def auth_events(request: Request, limit: int = 50):
        sess, err = need_session(request)
        if err:
            return err
        return {"ok": True, "events": accounts.events(sess.user, limit)}

    def signed_out(request: Request, sess, what: str, n: int, here: bool) -> JSONResponse:
        ip = phone.client_ip(request.client.host if request.client else None)
        accounts.event("signed_out", sess.method, sess.user.email, sess.user.id,
                       f"{what}: {n} session(s)", str(ip) if ip else None,
                       request.headers.get("user-agent"))
        resp = JSONResponse({"ok": True, "revoked": n, "signed_out_here": here})
        if here:
            clear_session_cookie(resp)
        return resp

    @app.post("/api/auth/signout")
    def auth_signout(request: Request):
        sess, err = need_session(request)
        if err:
            return err
        n = 1 if accounts.revoke_one(sess.user.id, sess.public_id, "signed out") else 0
        return signed_out(request, sess, "signed out this device", n, True)

    @app.post("/api/auth/signout-others")
    def auth_signout_others(request: Request):
        sess, err = need_session(request)
        if err:
            return err
        n = accounts.revoke_others(sess.user.id, sess.public_id)
        return signed_out(request, sess, "signed out other devices", n, False)

    @app.post("/api/auth/signout-all")
    def auth_signout_all(request: Request):
        sess, err = need_session(request)
        if err:
            return err
        n = accounts.revoke_all(sess.user.id, reason="signed out (all)")
        return signed_out(request, sess, "signed out everywhere", n, True)

    @app.post("/api/auth/sessions/{public_id}/revoke")
    def auth_revoke_one(public_id: str, request: Request):
        sess, err = need_session(request)
        if err:
            return err
        if not accounts.revoke_one(sess.user.id, public_id, "signed out from another device"):
            return _err(404, "session_not_found", "No active session of yours with that id")
        return signed_out(request, sess, "signed out one device", 1,
                          public_id == sess.public_id)

    # ---- health ---------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "app": "drill", "schema": db.SCHEMA_VERSION}

    # ---- store ----------------------------------------------------------------------
    @app.get("/api/store")
    def store_list(request: Request, prefix: str = ""):
        c = conn(request)
        try:
            return {"keys": db.list_keys(c, prefix)}
        finally:
            c.close()

    @app.get("/api/store/{key:path}")
    def store_get(key: str, request: Request):
        if not key:
            return _err(400, "bad_key", "Key must not be empty")
        c = conn(request)
        try:
            row = db.get(c, key)
        finally:
            c.close()
        if row is None:
            # 204, not 404: a missing key is a normal answer ("nothing stored yet", e.g. the
            # progress of a deck never studied), and browsers log every 404 as a red
            # "Failed to load resource" line. A stored JSON null is 200 "null".
            return Response(status_code=204)
        return Response(content=row[0].encode("utf-8"),
                        media_type="application/json; charset=utf-8",
                        headers={"X-Updated-At": row[1]})

    @app.put("/api/store/{key:path}")
    async def store_put(key: str, request: Request):
        if not key:
            return _err(400, "bad_key", "Key must not be empty")
        raw = await request.body()
        try:
            text = raw.decode("utf-8")
            json.loads(text, parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError) as e:
            return _err(400, "bad_json", f"Body must be one JSON value in UTF-8 ({e})")
        c = conn(request)
        try:
            status, ts = await asyncio.to_thread(db.put, c, key, text)
        finally:
            c.close()
        return {"ok": True, "key": key, "status": status, "updated_at": ts}

    @app.delete("/api/store/{key:path}")
    def store_delete(key: str, request: Request):
        if not key:
            return _err(400, "bad_key", "Key must not be empty")
        c = conn(request)
        try:
            existed = db.delete(c, key)
        finally:
            c.close()
        if not existed:
            return _err(404, "not_found", "No value stored under this key", key=key)
        return {"ok": True, "key": key, "deleted": True}

    # ---- import ---------------------------------------------------------------------
    @app.post("/api/import")
    def do_import(request: Request):
        from .importer import ConfirmationRequired, ImportError_, run_import
        try:
            # confirm=None: new keys are added, but no existing key is ever changed from here
            rep = run_import(us_of(request), confirm=None)
        except ConfirmationRequired as e:
            return _err(409, "confirmation_required", str(e), plan=e.plan)
        except ImportError_ as e:
            return _err(409, "import_stopped", str(e))
        return {"ok": True, "kv_writes": rep.kv_writes, "history_rows": rep.history_rows,
                "added_keys": rep.added_keys, "undecided": rep.undecided,
                "skipped": rep.skipped, "snapshot": rep.snapshot.name if rep.snapshot else None,
                "report": rep.lines}

    # ---- module library (Phase 6). See server/modules.py ------------------------------
    @app.get("/api/modules")
    def modules_list(request: Request):
        return {"modules": modules.list_modules(us_of(request))}

    @app.post("/api/modules")
    async def modules_upload(request: Request, name: str = ""):
        from urllib.parse import unquote
        file_name = name or unquote(request.headers.get("x-file-name") or "")
        if not file_name.strip():
            return _err(400, "no_name", "Send the file name as ?name= or an X-File-Name header")
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > modules.MAX_UPLOAD:
            return _err(413, "too_large", f"Upload is larger than {modules.MAX_UPLOAD} bytes")
        us = us_of(request)
        tmp = modules.new_temp(us)
        h, size, head = hashlib.sha256(), 0, b""
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > modules.MAX_UPLOAD:
                        raise modules.ModuleError(413, "too_large",
                                                  f"Upload is larger than {modules.MAX_UPLOAD} bytes")
                    if len(head) < 5:
                        head += chunk[:5 - len(head)]
                    h.update(chunk)
                    await asyncio.to_thread(f.write, chunk)
            if not head.startswith(b"%PDF-"):
                raise modules.ModuleError(415, "not_pdf", "That file is not a PDF")
            return await asyncio.to_thread(modules.finish_upload, us, tmp, h.hexdigest(),
                                           size, file_name, md_for(us))
        except modules.ModuleError as e:
            return _err(e.status, e.kind, e.message)
        finally:
            tmp.unlink(missing_ok=True)     # our own temp file only (moved away on success)

    @app.post("/api/modules/{sha}/deck")
    async def modules_deck(sha: str, request: Request):
        try:
            body = json.loads((await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("deck_id"), str)                 or not body["deck_id"]:
            return _err(400, "bad_request", 'Body must be {"deck_id": "<id>"}')
        pages = body.get("pages") if isinstance(body.get("pages"), int) else None
        prev = body.get("previous_sha") if isinstance(body.get("previous_sha"), str) else None
        try:
            us = us_of(request)
            return await asyncio.to_thread(modules.record_deck, us, sha.lower(),
                                           body["deck_id"], md_for(us), pages, prev)
        except modules.ModuleError as e:
            return _err(e.status, e.kind, e.message)

    # ---- AI (Phase 5): Qwen by default, `claude -p` when online. See server/ai.py --------
    router = ai.Router(ai_config if ai_config is not None else ai.load_ai_config())
    app.state.ai_router = router

    @app.get("/api/ai/route")
    async def ai_which_model():
        return await router.route_for_text()

    @app.post("/api/ai")
    async def ai_route(request: Request):
        try:
            body = json.loads((await request.body()).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            body = None
        try:
            return await router.handle(body)
        except ai.AIError as e:
            return JSONResponse(e.body(), status_code=e.status)

    # ---- the app itself ---------------------------------------------------------------
    if not (app_dir / "favicon.ico").is_file():
        @app.get("/favicon.ico", include_in_schema=False)
        def no_favicon():
            # the app has no icon; answer "nothing" rather than 404, so the console stays clean
            return Response(status_code=204)

    if (app_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(app_dir), html=True), name="app")
    else:
        @app.get("/", response_class=HTMLResponse)
        def placeholder():
            return PLACEHOLDER

    return app
