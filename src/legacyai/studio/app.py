"""Same-origin browser application and API."""
import hashlib
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .archive_api import router as archive_router
from .clip_api import router as clip_router
from .db import connect, initialize
from .jobs import run_worker
from .models import Credentials
from .workflow_api import router as workflow_router


def create_app():
    production = os.environ.get("LEGACY_ENV")=="production"
    demo = os.environ.get("LEGACY_DEMO")=="1"
    if production and demo:
        raise RuntimeError("Demo sign-in must be disabled in production")

    @asynccontextmanager
    async def lifespan(app):
        initialize()
        stop = threading.Event()
        thread = None
        if os.environ.get("LEGACY_EMBEDDED_WORKER")=="1":
            thread = threading.Thread(target=run_worker,args=(stop,),daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=3)

    app = FastAPI(title="Legacy Studio",version="0.3.0",lifespan=lifespan,
                  docs_url=None if production else "/api/docs",redoc_url=None)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        length = request.headers.get("content-length", "0")
        limit = int(os.environ.get("LEGACY_UPLOAD_MB","1000"))*1024*1024+1024*1024
        if length.isdigit() and int(length)>limit:
            return JSONResponse({"detail":"Upload exceeds the server limit"},status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
            "frame-src https://www.youtube-nocookie.com; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if request.url.path.startswith(("/api/","/delivery/")):
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.get("/health")
    def health():
        with connect() as con:
            con.execute("SELECT 1").fetchone()
        return {"status":"ok","version":"0.3.0"}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"demo":demo,"product":"Legacy Studio"}

    @app.post("/api/login")
    def login(data: Credentials, request: Request, response: Response):
        return auth.login(request,response,data.email,data.password)

    @app.post("/api/demo")
    def demo_login(request: Request, response: Response):
        if not demo:
            raise HTTPException(404,"Demo sign-in is disabled")
        return auth.login(request,response,"demo@legacy.local","legacy-local-demo")

    @app.get("/api/me")
    def me(actor=Depends(auth.user)):
        return {**actor,"demo":demo}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, actor=Depends(auth.user)):
        token = request.cookies.get(auth.COOKIE,"")
        with connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie(auth.COOKIE)
        return {"ok":True}

    app.include_router(archive_router)
    app.include_router(clip_router)
    app.include_router(workflow_router)
    root = Path(os.environ.get("LEGACY_WEB_DIR",str(Path(__file__).resolve().parents[3]/"apps"/"web")))
    if not root.exists():
        root = Path.cwd()/"apps"/"web"
    app.mount("/static",StaticFiles(directory=root),name="static")

    @app.get("/")
    def index():
        return FileResponse(root/"index.html",headers={"Cache-Control":"no-cache"})

    return app
