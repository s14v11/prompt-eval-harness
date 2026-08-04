"""CRUD and version-history endpoints for prompts."""

from __future__ import annotations

import difflib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from prompt_eval.database import get_db
from prompt_eval.models import Prompt, PromptVersion
from prompt_eval.schemas import (
    PromptCreate,
    PromptDiff,
    PromptRead,
    PromptSummary,
    PromptVersionCreate,
    PromptVersionRead,
)
from prompt_eval.services.templater import TemplateRenderError, extract_variables

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _get_prompt_or_404(db: Session, prompt_id: str) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt {prompt_id!r} not found.")
    return prompt


@router.get("", response_model=list[PromptSummary])
def list_prompts(db: Session = Depends(get_db)) -> list[Prompt]:
    """List all prompts (without their full version history)."""
    return list(db.scalars(select(Prompt).order_by(Prompt.updated_at.desc())))


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)) -> Prompt:
    """Create a new prompt along with its first version (version 1)."""
    existing = db.scalar(select(Prompt).where(Prompt.name == payload.name))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Prompt named {payload.name!r} already exists.")

    try:
        variables = extract_variables(payload.template)
    except TemplateRenderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    prompt = Prompt(name=payload.name, description=payload.description)
    prompt.versions.append(
        PromptVersion(
            version_number=1,
            template=payload.template,
            variables=variables,
            commit_message="Initial version",
        )
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("/{prompt_id}", response_model=PromptRead)
def get_prompt(prompt_id: str, db: Session = Depends(get_db)) -> Prompt:
    """Fetch a prompt and its full version history."""
    return _get_prompt_or_404(db, prompt_id)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a prompt and all of its versions."""
    prompt = _get_prompt_or_404(db, prompt_id)
    db.delete(prompt)
    db.commit()


@router.post("/{prompt_id}/versions", response_model=PromptVersionRead, status_code=status.HTTP_201_CREATED)
def create_prompt_version(
    prompt_id: str, payload: PromptVersionCreate, db: Session = Depends(get_db)
) -> PromptVersion:
    """Add a new immutable version to an existing prompt."""
    prompt = _get_prompt_or_404(db, prompt_id)

    try:
        variables = extract_variables(payload.template)
    except TemplateRenderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    next_version_number = max((v.version_number for v in prompt.versions), default=0) + 1
    version = PromptVersion(
        prompt_id=prompt.id,
        version_number=next_version_number,
        template=payload.template,
        variables=variables,
        commit_message=payload.commit_message,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


@router.get("/{prompt_id}/versions", response_model=list[PromptVersionRead])
def list_prompt_versions(prompt_id: str, db: Session = Depends(get_db)) -> list[PromptVersion]:
    """List all versions of a prompt, oldest first."""
    prompt = _get_prompt_or_404(db, prompt_id)
    return prompt.versions


@router.get("/{prompt_id}/diff", response_model=PromptDiff)
def diff_prompt_versions(
    prompt_id: str, from_version: int, to_version: int, db: Session = Depends(get_db)
) -> PromptDiff:
    """Return a unified diff between two versions of a prompt's template."""
    prompt = _get_prompt_or_404(db, prompt_id)
    versions_by_number = {v.version_number: v for v in prompt.versions}

    for number in (from_version, to_version):
        if number not in versions_by_number:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Prompt {prompt_id!r} has no version {number}.")

    from_text = versions_by_number[from_version].template.splitlines(keepends=True)
    to_text = versions_by_number[to_version].template.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        from_text, to_text, fromfile=f"v{from_version}", tofile=f"v{to_version}"
    )
    return PromptDiff(
        prompt_id=prompt_id, from_version=from_version, to_version=to_version, diff="".join(diff_lines)
    )
