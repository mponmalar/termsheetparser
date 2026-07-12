"""Term Sheet Parser — application entrypoint.

All settings (port, LLM provider, database, …) are read from .env at the
project root.  See .env for the full reference.

Quick start:
    ./run.sh                                   # reads .env automatically
    # or manually:
    uvicorn backend.app.main:app --port 8000
GUI:  http://localhost:8000
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import APP_VERSION
from .db.database import init_db

app = FastAPI(title="Term Sheet Parser",
              description="Multi-agent EQD term-sheet extraction with "
                          "self-learning feedback loop",
              version=APP_VERSION)

init_db()
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "version": APP_VERSION}


# Allow running as a script: python -m backend.app.main
if __name__ == "__main__":
    import uvicorn
    from .config import TSP_HOST, TSP_LOG_LEVEL, TSP_PORT, TSP_RELOAD
    uvicorn.run("backend.app.main:app",
                host=TSP_HOST, port=TSP_PORT,
                reload=TSP_RELOAD, log_level=TSP_LOG_LEVEL)
