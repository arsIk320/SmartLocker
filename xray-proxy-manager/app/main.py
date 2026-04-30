from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_domains import router as domains_router
from app.api.routes_system import router as system_router
from app.api.routes_users import router as users_router
from app.api.ui import router as ui_router
from app.database import Base, engine
from app.services.xray import ensure_runtime_files


Base.metadata.create_all(bind=engine)
ensure_runtime_files()

app = FastAPI(title="Xray Proxy Manager", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

app.include_router(ui_router)
app.include_router(users_router)
app.include_router(domains_router)
app.include_router(system_router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
