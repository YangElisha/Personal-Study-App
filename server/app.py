"""The FastAPI application. Contract: docs/API.md."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ai, db, modules, snapshots
from .settings import REPO_ROOT, Settings

log = logging.getLogger("drill")

# Windows' registry often maps .woff2 to application/octet-stream (or nothing); fonts are
# vendored in app/vendor/fonts, so give them their proper types.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}

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
               modules_md_paths: "list[Path] | None" = None) -> FastAPI:
    app_dir = REPO_ROOT / "app" if app_dir is None else app_dir
    md_paths = (modules.default_md_paths(settings) if modules_md_paths is None
                else modules_md_paths)

    async def daily_snapshots():
        while True:
            await asyncio.sleep(daily_check_seconds)
            try:
                if snapshots.daily_due(settings):
                    p = await asyncio.to_thread(snapshots.take_snapshot, settings)
                    log.info("daily snapshot %s", p)
            except Exception:                       # never let the loop die
                log.exception("daily snapshot failed")

    @asynccontextmanager
    async def lifespan(_app):
        db.init_db(settings.db_path)
        p = snapshots.take_snapshot(settings)
        log.info("snapshot on start: %s", p)
        task = asyncio.create_task(daily_snapshots())
        try:
            yield
        finally:
            task.cancel()
            try:
                db.checkpoint(settings.db_path)
            except Exception:
                log.exception("checkpoint on shutdown failed")

    app = FastAPI(title="Drill local server", lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.settings = settings

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # DNS-rebinding guard: only answer requests addressed to this PC by name.
        host_header = (request.headers.get("host") or "").strip().lower()
        host, _, port = host_header.partition(":")
        if host not in ALLOWED_HOSTS:
            return _err(403, "forbidden_host", f"Host {host_header!r} is not allowed")
        # Only the app's own page may change anything. A state-changing request that carries
        # an Origin header (browsers always send one on cross-site requests, and "null" from
        # sandboxed frames and file:// pages) must come from this server's own origin.
        # Requests with no Origin (curl, the CLI tools, same-origin navigation) are allowed.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None:
                own = {f"http://{h}" + (f":{port}" if port else "") for h in ALLOWED_HOSTS}
                if origin.strip().lower().rstrip("/") not in own:
                    return _err(403, "forbidden_origin", f"Origin {origin!r} may not write here")
        resp = await call_next(request)
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"      # data: never from a cache
        else:
            resp.headers["Cache-Control"] = "no-cache"      # app files: revalidate
        return resp

    def conn():
        return db.connect(settings.db_path)

    # ---- health ---------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "app": "drill", "schema": db.SCHEMA_VERSION}

    # ---- store ----------------------------------------------------------------------
    @app.get("/api/store")
    def store_list(prefix: str = ""):
        c = conn()
        try:
            return {"keys": db.list_keys(c, prefix)}
        finally:
            c.close()

    @app.get("/api/store/{key:path}")
    def store_get(key: str):
        if not key:
            return _err(400, "bad_key", "Key must not be empty")
        c = conn()
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
        c = conn()
        try:
            status, ts = await asyncio.to_thread(db.put, c, key, text)
        finally:
            c.close()
        return {"ok": True, "key": key, "status": status, "updated_at": ts}

    @app.delete("/api/store/{key:path}")
    def store_delete(key: str):
        if not key:
            return _err(400, "bad_key", "Key must not be empty")
        c = conn()
        try:
            existed = db.delete(c, key)
        finally:
            c.close()
        if not existed:
            return _err(404, "not_found", "No value stored under this key", key=key)
        return {"ok": True, "key": key, "deleted": True}

    # ---- import ---------------------------------------------------------------------
    @app.post("/api/import")
    def do_import():
        from .importer import ConfirmationRequired, ImportError_, run_import
        try:
            # confirm=None: new keys are added, but no existing key is ever changed from here
            rep = run_import(settings, confirm=None)
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
    def modules_list():
        return {"modules": modules.list_modules(settings)}

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
        tmp = modules.new_temp(settings)
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
            return await asyncio.to_thread(modules.finish_upload, settings, tmp, h.hexdigest(),
                                           size, file_name, md_paths)
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
            return await asyncio.to_thread(modules.record_deck, settings, sha.lower(),
                                           body["deck_id"], md_paths, pages, prev)
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
