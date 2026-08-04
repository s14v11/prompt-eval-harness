"""Pydantic schemas for request/response validation across the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from prompt_eval.models import EvaluationMethod, Provider, RunStatus

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class PromptVersionCreate(BaseModel):
    """Payload for creating a new version of an existing prompt."""

    template: str = Field(..., description="Jinja2 template body for this version.")
    commit_message: str | None = Field(None, description="Short note describing the change.")


class PromptVersionRead(BaseModel):
    """A prompt version as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt_id: str
    version_number: int
    template: str
    variables: list[str]
    commit_message: str | None
    created_at: datetime


class PromptCreate(BaseModel):
    """Payload for creating a new prompt (and its initial version)."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    template: str = Field(..., description="Jinja2 template body for version 1.")


class PromptRead(BaseModel):
    """A prompt, including its version history, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[PromptVersionRead] = []


class PromptSummary(BaseModel):
    """A lightweight prompt representation for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class PromptDiff(BaseModel):
    """A unified diff between two versions of a prompt."""

    prompt_id: str
    from_version: int
    to_version: int
    diff: str


# ---------------------------------------------------------------------------
# Test suites / cases
# ---------------------------------------------------------------------------


class TestCaseCreate(BaseModel):
    """Payload for creating a test case within a suite."""

    name: str = Field(..., min_length=1, max_length=255)
    input_variables: dict = Field(default_factory=dict)
    expected_output: str | None = None
    evaluation_method: EvaluationMethod = EvaluationMethod.EXACT_MATCH
    evaluation_criteria: dict = Field(default_factory=dict)


class TestCaseRead(BaseModel):
    """A test case as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_id: str
    name: str
    input_variables: dict
    expected_output: str | None
    evaluation_method: EvaluationMethod
    evaluation_criteria: dict
    created_at: datetime


class TestSuiteCreate(BaseModel):
    """Payload for creating a test suite."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class TestSuiteRead(BaseModel):
    """A test suite, including its test cases, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    created_at: datetime
    test_cases: list[TestCaseRead] = []


# ---------------------------------------------------------------------------
# Model configs
# ---------------------------------------------------------------------------


class ModelConfigCreate(BaseModel):
    """Payload for registering a model configuration."""

    name: str = Field(..., min_length=1, max_length=255)
    provider: Provider
    model_id: str = Field(..., description='Provider-native model id, e.g. "gpt-4o".')
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, gt=0)
    extra_params: dict = Field(default_factory=dict)


class ModelConfigRead(BaseModel):
    """A model configuration as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: Provider
    model_id: str
    temperature: float
    max_tokens: int
    extra_params: dict
    created_at: datetime


# ---------------------------------------------------------------------------
# Eval runs / results
# ---------------------------------------------------------------------------


class EvalRunCreate(BaseModel):
    """Payload for launching a new evaluation run."""

    name: str = Field(..., min_length=1, max_length=255)
    prompt_version_id: str
    suite_id: str
    model_config_ids: list[str] = Field(..., min_length=1)


class EvalResultRead(BaseModel):
    """A single test-case x model result as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    test_case_id: str
    model_config_id: str
    prompt_version_id: str
    rendered_prompt: str
    raw_output: str | None
    score: float | None
    passed: bool | None
    evaluation_details: dict
    latency_ms: float | None
    error: str | None
    created_at: datetime


class EvalRunRead(BaseModel):
    """An evaluation run, including summary status, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prompt_version_id: str
    suite_id: str
    status: RunStatus
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class EvalRunDetail(EvalRunRead):
    """An evaluation run with its full set of results attached."""

    results: list[EvalResultRead] = []


class EvalRunSummary(BaseModel):
    """Aggregate pass rate / average score per model for a completed run."""

    model_config_id: str
    model_name: str
    total: int
    passed: int
    average_score: float | None
