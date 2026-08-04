"""Evaluation engine: scores a model's output against a test case's expectations.

Three strategies are supported:
    * exact_match: normalized string equality.
    * semantic_similarity: a lightweight, dependency-free similarity ratio
      (difflib's SequenceMatcher) compared against a configurable threshold.
      This avoids requiring an embeddings API/model just to run tests.
    * llm_as_judge: delegates scoring to an LLM, which returns a 0-100 score
      and a short rationale for a configurable rubric.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from prompt_eval.config import Settings, get_settings
from prompt_eval.models import EvaluationMethod, Provider
from prompt_eval.services.llm_client import LLMClient, LLMClientError

_JUDGE_PROMPT = """You are an impartial evaluator. Score how well the ACTUAL OUTPUT satisfies \
the EXPECTED OUTPUT / rubric below, on a scale of 0 to 100.

Rubric:
{rubric}

Expected output:
{expected_output}

Actual output:
{actual_output}

Respond with ONLY a JSON object of the form:
{{"score": <integer 0-100>, "reasoning": "<one sentence>"}}
"""


class EvaluationError(Exception):
    """Raised when an evaluation cannot be completed (e.g. judge call fails)."""


@dataclass
class EvaluationOutcome:
    """The result of scoring one model output against one test case."""

    score: float | None
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


def _normalize(text: str, *, case_sensitive: bool, strip_whitespace: bool) -> str:
    """Apply normalization rules before comparing two strings."""
    if strip_whitespace:
        text = text.strip()
    if not case_sensitive:
        text = text.lower()
    return text


def _score_exact_match(actual: str, expected: str, criteria: dict[str, Any]) -> EvaluationOutcome:
    case_sensitive = bool(criteria.get("case_sensitive", False))
    strip_whitespace = bool(criteria.get("strip_whitespace", True))
    normalized_actual = _normalize(actual, case_sensitive=case_sensitive, strip_whitespace=strip_whitespace)
    normalized_expected = _normalize(
        expected, case_sensitive=case_sensitive, strip_whitespace=strip_whitespace
    )
    passed = normalized_actual == normalized_expected
    return EvaluationOutcome(score=1.0 if passed else 0.0, passed=passed, details={"method": "exact_match"})


def _score_semantic_similarity(actual: str, expected: str, criteria: dict[str, Any]) -> EvaluationOutcome:
    threshold = float(criteria.get("threshold", 0.8))
    ratio = SequenceMatcher(a=expected.strip().lower(), b=actual.strip().lower()).ratio()
    passed = ratio >= threshold
    return EvaluationOutcome(
        score=ratio,
        passed=passed,
        details={"method": "semantic_similarity", "threshold": threshold, "similarity_ratio": ratio},
    )


def _parse_judge_response(raw_text: str) -> tuple[float, str]:
    """Extract a 0-100 score and rationale from a judge model's raw text response."""
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise EvaluationError(f"Judge response did not contain a JSON object: {raw_text!r}")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Judge response was not valid JSON: {raw_text!r}") from exc
    score = float(payload.get("score", 0))
    reasoning = str(payload.get("reasoning", ""))
    return score, reasoning


class Evaluator:
    """Scores model outputs against test-case expectations using pluggable strategies."""

    def __init__(self, llm_client: LLMClient | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._llm_client = llm_client or LLMClient(self._settings)

    async def evaluate(
        self,
        method: EvaluationMethod,
        actual_output: str,
        expected_output: str | None,
        criteria: dict[str, Any],
    ) -> EvaluationOutcome:
        """Score `actual_output` using the given evaluation `method`.

        Args:
            method: Which evaluation strategy to apply.
            actual_output: The model's raw generated text.
            expected_output: The reference answer, if any.
            criteria: Method-specific configuration (thresholds, rubric, judge model, etc.).

        Returns:
            An `EvaluationOutcome` with a normalized score and pass/fail verdict.

        Raises:
            EvaluationError: If the method is unsupported or requires data that is missing.
        """
        if method == EvaluationMethod.EXACT_MATCH:
            if expected_output is None:
                raise EvaluationError("exact_match requires an expected_output.")
            return _score_exact_match(actual_output, expected_output, criteria)

        if method == EvaluationMethod.SEMANTIC_SIMILARITY:
            if expected_output is None:
                raise EvaluationError("semantic_similarity requires an expected_output.")
            return _score_semantic_similarity(actual_output, expected_output, criteria)

        if method == EvaluationMethod.LLM_AS_JUDGE:
            return await self._score_llm_as_judge(actual_output, expected_output, criteria)

        raise EvaluationError(f"Unsupported evaluation method: {method}")

    async def _score_llm_as_judge(
        self, actual_output: str, expected_output: str | None, criteria: dict[str, Any]
    ) -> EvaluationOutcome:
        rubric = criteria.get("rubric", "The actual output should closely match the expected output.")
        provider = Provider(criteria.get("provider", Provider.OPENAI.value))
        model_id = criteria.get("model_id", self._settings.default_judge_model)
        pass_threshold = float(criteria.get("pass_threshold", 70))

        judge_prompt = _JUDGE_PROMPT.format(
            rubric=rubric,
            expected_output=expected_output or "(none provided)",
            actual_output=actual_output,
        )
        try:
            response = await self._llm_client.generate(
                provider=provider, model_id=model_id, prompt=judge_prompt, temperature=0.0, max_tokens=200
            )
        except LLMClientError as exc:
            raise EvaluationError(f"LLM-as-judge call failed: {exc}") from exc

        score, reasoning = _parse_judge_response(response.text)
        normalized_score = score / 100.0
        passed = score >= pass_threshold
        return EvaluationOutcome(
            score=normalized_score,
            passed=passed,
            details={
                "method": "llm_as_judge",
                "raw_score": score,
                "reasoning": reasoning,
                "judge_provider": provider.value,
                "judge_model": model_id,
                "pass_threshold": pass_threshold,
            },
        )
