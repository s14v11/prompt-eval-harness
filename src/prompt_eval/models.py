"""SQLAlchemy ORM models for prompts, test suites, model configs, and eval runs."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from prompt_eval.database import Base


def _uuid() -> str:
    """Generate a URL-safe unique identifier for primary keys."""
    return uuid.uuid4().hex


def _now() -> datetime:
    """Return the current UTC time, used as a default for timestamp columns."""
    return datetime.now(UTC)


class Provider(str, enum.Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class EvaluationMethod(str, enum.Enum):
    """Supported evaluation strategies for a test case."""

    EXACT_MATCH = "exact_match"
    STRING_SIMILARITY = "string_similarity"
    LLM_AS_JUDGE = "llm_as_judge"


class RunStatus(str, enum.Enum):
    """Lifecycle states of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Prompt(Base):
    """A named, versioned prompt template."""

    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", order_by="PromptVersion.version_number"
    )


class PromptVersion(Base):
    """A single immutable version of a prompt's Jinja2 template."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version_number", name="uq_prompt_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompts.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    prompt: Mapped[Prompt] = relationship(back_populates="versions")
    results: Mapped[list[EvalResult]] = relationship(back_populates="prompt_version")


class TestSuite(Base):
    """A named collection of test cases used to evaluate prompts."""

    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    test_cases: Mapped[list[TestCase]] = relationship(
        back_populates="suite", cascade="all, delete-orphan"
    )
    runs: Mapped[list[EvalRun]] = relationship(back_populates="suite")


class TestCase(Base):
    """A single input/expected-output pair with an evaluation strategy."""

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    suite_id: Mapped[str] = mapped_column(ForeignKey("test_suites.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_variables: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_method: Mapped[EvaluationMethod] = mapped_column(
        Enum(EvaluationMethod), default=EvaluationMethod.EXACT_MATCH
    )
    evaluation_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    suite: Mapped[TestSuite] = relationship(back_populates="test_cases")
    results: Mapped[list[EvalResult]] = relationship(back_populates="test_case")


class ModelConfig(Base):
    """Configuration for a specific model+provider combination."""

    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    extra_params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    results: Mapped[list[EvalResult]] = relationship(back_populates="model_config")


eval_run_model_configs = Table(
    "eval_run_model_configs",
    Base.metadata,
    Column("run_id", String(32), ForeignKey("eval_runs.id"), primary_key=True),
    Column("model_config_id", String(32), ForeignKey("model_configs.id"), primary_key=True),
)


class EvalRun(Base):
    """A batch evaluation run of one prompt version against one suite across N models."""

    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id"), nullable=False)
    suite_id: Mapped[str] = mapped_column(ForeignKey("test_suites.id"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    prompt_version: Mapped[PromptVersion] = relationship()
    suite: Mapped[TestSuite] = relationship(back_populates="runs")
    model_configs: Mapped[list[ModelConfig]] = relationship(secondary=eval_run_model_configs)
    results: Mapped[list[EvalResult]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    """The outcome of running one test case against one model for one eval run."""

    __tablename__ = "eval_results"

    __table_args__ = (
        UniqueConstraint("run_id", "test_case_id", "model_config_id", name="uq_eval_result_run_case_model"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id"), nullable=False)
    test_case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id"), nullable=False)
    model_config_id: Mapped[str] = mapped_column(ForeignKey("model_configs.id"), nullable=False)
    prompt_version_id: Mapped[str] = mapped_column(ForeignKey("prompt_versions.id"), nullable=False)

    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    evaluation_details: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    run: Mapped[EvalRun] = relationship(back_populates="results")
    test_case: Mapped[TestCase] = relationship(back_populates="results")
    model_config: Mapped[ModelConfig] = relationship(back_populates="results")
    prompt_version: Mapped[PromptVersion] = relationship(back_populates="results")
