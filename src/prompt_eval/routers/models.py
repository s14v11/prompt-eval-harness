"""CRUD endpoints for LLM model configurations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from prompt_eval.database import get_db
from prompt_eval.models import ModelConfig
from prompt_eval.schemas import ModelConfigCreate, ModelConfigRead

router = APIRouter(prefix="/model-configs", tags=["model-configs"])


@router.get("", response_model=list[ModelConfigRead])
def list_model_configs(db: Session = Depends(get_db)) -> list[ModelConfig]:
    """List all registered model configurations."""
    return list(db.scalars(select(ModelConfig).order_by(ModelConfig.created_at.desc())))


@router.post("", response_model=ModelConfigRead, status_code=status.HTTP_201_CREATED)
def create_model_config(payload: ModelConfigCreate, db: Session = Depends(get_db)) -> ModelConfig:
    """Register a new model configuration (provider + model id + generation params)."""
    existing = db.scalar(select(ModelConfig).where(ModelConfig.name == payload.name))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Model config named {payload.name!r} already exists."
        )
    model_config = ModelConfig(**payload.model_dump())
    db.add(model_config)
    db.commit()
    db.refresh(model_config)
    return model_config


@router.get("/{model_config_id}", response_model=ModelConfigRead)
def get_model_config(model_config_id: str, db: Session = Depends(get_db)) -> ModelConfig:
    """Fetch a single model configuration by id."""
    model_config = db.get(ModelConfig, model_config_id)
    if model_config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model config {model_config_id!r} not found.")
    return model_config


@router.delete("/{model_config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_config(model_config_id: str, db: Session = Depends(get_db)) -> None:
    """Delete a model configuration."""
    model_config = db.get(ModelConfig, model_config_id)
    if model_config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model config {model_config_id!r} not found.")
    db.delete(model_config)
    db.commit()
