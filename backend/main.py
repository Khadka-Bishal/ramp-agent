from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Ramp Agent", version="0.1.0", lifespan=lifespan)

allow_credentials = "*" not in settings.cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


from backend.routes.sessions import router as sessions_router
from backend.routes.events import router as events_router
from backend.routes.artifacts import router as artifacts_router

app.include_router(sessions_router)
app.include_router(events_router)
app.include_router(artifacts_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
