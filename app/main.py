"""OpsScope 入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import database
from .api import router

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app():
    database.init_db()
    app = FastAPI(title="OpsScope", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    if (FRONTEND_DIR / "static").exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    return app


app = create_app()
