"""Celery application and the batch-evaluation background task.

`run_evaluation_task` renders the prompt for every (test case x model config)
pair in a run, calls the model, scores the output, and persists an
`EvalResult` row per pair — updating `EvalRun.status` as it goes so clients
polling `GET /runs/{id}` or the `/runs/{id}/ws` WebSocket see live progress.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from celery import Celery

from prompt_eval.config import get_settings
from prompt_eval.database import SessionLocal
from prompt_eval.models import EvalResult, EvalRun, RunStatus
from prompt_eval.services.evaluator import EvaluationError, Evaluator
from prompt_eval.services.llm_client import LLMClient, LLMClientError
from prompt_eval.services.templater import TemplateRenderError, render_prompt

settings = get_settings()

celery_app = Celery(
    "prompt_eval",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.environment == "test",
    task_eager_propagates=True,
)


@celery_app.task(name="prompt_eval.run_evaluation")
def run_evaluation_task(run_id: str) -> None:
    """Celery entrypoint: synchronously drive the async evaluation coroutine."""
    asyncio.run(_run_evaluation(run_id))


async def _run_evaluation(run_id: str) -> None:
    """Execute every test-case x model-config pair for an eval run and persist results."""
    db = SessionLocal()
    llm_client = LLMClient()
    evaluator = Evaluator(llm_client=llm_client)
    try:
        run = db.get(EvalRun, run_id)
        if run is None:
            return

        run.status = RunStatus.RUNNING
        db.commit()

        template = run.prompt_version.template
        test_cases = list(run.suite.test_cases)
        model_configs = list(run.model_configs)

        for test_case in test_cases:
            for model_config in model_configs:
                result = EvalResult(
                    run_id=run.id,
                    test_case_id=test_case.id,
                    model_config_id=model_config.id,
                    prompt_version_id=run.prompt_version_id,
                    rendered_prompt="",
                )
                try:
                    rendered = render_prompt(template, test_case.input_variables)
                    result.rendered_prompt = rendered

                    response = await llm_client.generate(
                        provider=model_config.provider,
                        model_id=model_config.model_id,
                        prompt=rendered,
                        temperature=model_config.temperature,
                        max_tokens=model_config.max_tokens,
                        extra_params=model_config.extra_params,
                    )
                    result.raw_output = response.text
                    result.latency_ms = response.latency_ms

                    outcome = await evaluator.evaluate(
                        method=test_case.evaluation_method,
                        actual_output=response.text,
                        expected_output=test_case.expected_output,
                        criteria=test_case.evaluation_criteria,
                    )
                    result.score = outcome.score
                    result.passed = outcome.passed
                    result.evaluation_details = outcome.details
                except (TemplateRenderError, LLMClientError, EvaluationError) as exc:
                    result.error = str(exc)
                    result.passed = False

                db.add(result)
                db.commit()

        run.status = RunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        # Record the failure on the run before re-raising so Celery still sees the error.
        run = db.get(EvalRun, run_id)
        if run is not None:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            db.commit()
        raise
    finally:
        db.close()
