"""Endpoints for launching evaluation runs, inspecting results, and exporting reports."""

from __future__ import annotations

import asyncio
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from prompt_eval.database import SessionLocal, get_db
from prompt_eval.models import EvalResult, EvalRun, ModelConfig, PromptVersion, RunStatus, TestSuite
from prompt_eval.schemas import EvalRunCreate, EvalRunDetail, EvalRunRead, EvalRunSummary
from prompt_eval.workers.celery_app import run_evaluation_task

router = APIRouter(prefix="/runs", tags=["runs"])


def _get_run_or_404(db: Session, run_id: str) -> EvalRun:
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Eval run {run_id!r} not found.")
    return run


@router.post("", response_model=EvalRunRead, status_code=status.HTTP_201_CREATED)
def create_run(payload: EvalRunCreate, db: Session = Depends(get_db)) -> EvalRun:
    """Create and enqueue a new evaluation run.

    The run is executed asynchronously by a Celery worker; poll `GET /runs/{id}`
    or open the `/runs/{id}/ws` WebSocket to observe progress.
    """
    prompt_version = db.get(PromptVersion, payload.prompt_version_id)
    if prompt_version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Prompt version {payload.prompt_version_id!r} not found."
        )
    suite = db.get(TestSuite, payload.suite_id)
    if suite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Test suite {payload.suite_id!r} not found.")

    model_configs = list(
        db.scalars(select(ModelConfig).where(ModelConfig.id.in_(payload.model_config_ids)))
    )
    missing = set(payload.model_config_ids) - {mc.id for mc in model_configs}
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model config(s) not found: {sorted(missing)}")

    run = EvalRun(
        name=payload.name,
        prompt_version_id=prompt_version.id,
        suite_id=suite.id,
        status=RunStatus.PENDING,
        model_configs=model_configs,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    run_evaluation_task.delay(run.id)
    return run


@router.get("", response_model=list[EvalRunRead])
def list_runs(db: Session = Depends(get_db)) -> list[EvalRun]:
    """List all evaluation runs, most recent first."""
    return list(db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc())))


@router.get("/{run_id}", response_model=EvalRunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)) -> EvalRun:
    """Fetch an evaluation run along with all of its per-test-case results."""
    return _get_run_or_404(db, run_id)


@router.get("/{run_id}/summary", response_model=list[EvalRunSummary])
def get_run_summary(run_id: str, db: Session = Depends(get_db)) -> list[EvalRunSummary]:
    """Return pass-rate and average-score aggregates, broken down by model."""
    run = _get_run_or_404(db, run_id)
    summaries: dict[str, EvalRunSummary] = {}
    for model_config in run.model_configs:
        results = [r for r in run.results if r.model_config_id == model_config.id]
        scored = [r.score for r in results if r.score is not None]
        summaries[model_config.id] = EvalRunSummary(
            model_config_id=model_config.id,
            model_name=model_config.name,
            total=len(results),
            passed=sum(1 for r in results if r.passed),
            average_score=(sum(scored) / len(scored)) if scored else None,
        )
    return list(summaries.values())


@router.get("/{run_id}/export")
def export_run(
    run_id: str, format: str = Query("json", pattern="^(json|csv)$"), db: Session = Depends(get_db)
) -> StreamingResponse:
    """Export a run's results as either JSON or CSV."""
    run = _get_run_or_404(db, run_id)
    rows = [
        {
            "test_case_id": r.test_case_id,
            "model_config_id": r.model_config_id,
            "rendered_prompt": r.rendered_prompt,
            "raw_output": r.raw_output,
            "score": r.score,
            "passed": r.passed,
            "latency_ms": r.latency_ms,
            "error": r.error,
        }
        for r in run.results
    ]

    if format == "json":
        buffer = io.StringIO(json.dumps(rows, indent=2))
        media_type = "application/json"
        filename = f"run-{run_id}.json"
    else:
        buffer = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        buffer.seek(0)
        media_type = "text/csv"
        filename = f"run-{run_id}.csv"

    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.websocket("/{run_id}/ws")
async def run_status_websocket(websocket: WebSocket, run_id: str) -> None:
    """Stream run status updates until the run completes, fails, or the client disconnects."""
    await websocket.accept()
    try:
        while True:
            db = SessionLocal()
            try:
                run = db.get(EvalRun, run_id)
                if run is None:
                    await websocket.send_json({"error": f"Eval run {run_id!r} not found."})
                    return
                completed = len(
                    db.scalars(select(EvalResult).where(EvalResult.run_id == run_id)).all()
                )
                await websocket.send_json(
                    {
                        "run_id": run.id,
                        "status": run.status.value,
                        "completed_results": completed,
                        "error": run.error,
                    }
                )
                if run.status in (RunStatus.COMPLETED, RunStatus.FAILED):
                    return
            finally:
                db.close()
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
