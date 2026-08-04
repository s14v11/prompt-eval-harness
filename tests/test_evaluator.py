"""Tests for the three evaluation strategies in `prompt_eval.services.evaluator`."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from prompt_eval.models import EvaluationMethod, Provider
from prompt_eval.services.evaluator import EvaluationError, Evaluator
from prompt_eval.services.llm_client import LLMResponse


@pytest.fixture()
def evaluator() -> Evaluator:
    return Evaluator(llm_client=AsyncMock())


async def test_exact_match_pass(evaluator):
    outcome = await evaluator.evaluate(
        EvaluationMethod.EXACT_MATCH, actual_output="  Paris ", expected_output="paris", criteria={}
    )
    assert outcome.passed is True
    assert outcome.score == 1.0


async def test_exact_match_fail_when_case_sensitive(evaluator):
    outcome = await evaluator.evaluate(
        EvaluationMethod.EXACT_MATCH,
        actual_output="Paris",
        expected_output="paris",
        criteria={"case_sensitive": True},
    )
    assert outcome.passed is False
    assert outcome.score == 0.0


async def test_exact_match_requires_expected_output(evaluator):
    with pytest.raises(EvaluationError):
        await evaluator.evaluate(
            EvaluationMethod.EXACT_MATCH, actual_output="x", expected_output=None, criteria={}
        )


async def test_semantic_similarity_passes_above_threshold(evaluator):
    outcome = await evaluator.evaluate(
        EvaluationMethod.SEMANTIC_SIMILARITY,
        actual_output="The quick brown fox jumps over the lazy dog",
        expected_output="The quick brown fox jumps over the lazy dog!",
        criteria={"threshold": 0.9},
    )
    assert outcome.passed is True
    assert outcome.score > 0.9


async def test_semantic_similarity_fails_below_threshold(evaluator):
    outcome = await evaluator.evaluate(
        EvaluationMethod.SEMANTIC_SIMILARITY,
        actual_output="completely unrelated text",
        expected_output="The quick brown fox",
        criteria={"threshold": 0.9},
    )
    assert outcome.passed is False


async def test_llm_as_judge_parses_score_and_passes():
    mock_client = AsyncMock()
    mock_client.generate.return_value = LLMResponse(
        text=json.dumps({"score": 85, "reasoning": "Matches the rubric closely."}),
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        latency_ms=12.0,
    )
    judge = Evaluator(llm_client=mock_client)

    outcome = await judge.evaluate(
        EvaluationMethod.LLM_AS_JUDGE,
        actual_output="A well-reasoned answer.",
        expected_output="A well-reasoned answer.",
        criteria={"pass_threshold": 70},
    )

    assert outcome.passed is True
    assert outcome.score == pytest.approx(0.85)
    assert outcome.details["reasoning"] == "Matches the rubric closely."


async def test_llm_as_judge_fails_below_threshold():
    mock_client = AsyncMock()
    mock_client.generate.return_value = LLMResponse(
        text=json.dumps({"score": 40, "reasoning": "Missing key details."}),
        provider=Provider.OPENAI,
        model_id="gpt-4o-mini",
        latency_ms=12.0,
    )
    judge = Evaluator(llm_client=mock_client)

    outcome = await judge.evaluate(
        EvaluationMethod.LLM_AS_JUDGE, actual_output="Nope", expected_output="Something", criteria={}
    )
    assert outcome.passed is False


async def test_llm_as_judge_raises_on_malformed_response():
    mock_client = AsyncMock()
    mock_client.generate.return_value = LLMResponse(
        text="not json at all", provider=Provider.OPENAI, model_id="gpt-4o-mini", latency_ms=1.0
    )
    judge = Evaluator(llm_client=mock_client)

    with pytest.raises(EvaluationError):
        await judge.evaluate(
            EvaluationMethod.LLM_AS_JUDGE, actual_output="x", expected_output="y", criteria={}
        )
