"""FastAPI application entrypoint: wires up routers, CORS, and startup hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prompt_eval.config import get_settings
from prompt_eval.database import init_db
from prompt_eval.routers import models, prompts, runs, tests

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database schema on startup (dev convenience; prod uses Alembic)."""
    init_db()
    yield


app = FastAPI(
    title="Prompt Eval Harness",
    description="Test, evaluate, and version LLM prompts across OpenAI, Anthropic, and Gemini.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(prompts.router, prefix="/api")
app.include_router(tests.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(runs.router, prefix="/api")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Liveness/readiness probe target for container orchestration."""
    return {"status": "ok", "environment": settings.environment}
