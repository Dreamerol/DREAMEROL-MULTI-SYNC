
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router

app = FastAPI(
    title="DREAMEROL FORK SYNC",
    docs_url=None,
    redoc_url=None,
)

app.include_router(router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app.mount(
    "/static",
    StaticFiles(directory=WEB_DIR),
    name="static",
)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")

