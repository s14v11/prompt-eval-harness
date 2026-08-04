.PHONY: install test run worker docker-build docker-up docker-down helm-install lint format clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test:
	$(VENV)/bin/pytest --cov=prompt_eval --cov-report=term-missing

run:
	$(VENV)/bin/uvicorn prompt_eval.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(VENV)/bin/celery -A prompt_eval.workers.celery_app worker --loglevel=info

lint:
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/mypy src

format:
	$(VENV)/bin/ruff format src tests

docker-build:
	docker compose build

docker-up:
	docker compose up --build

docker-down:
	docker compose down

helm-install:
	helm upgrade --install prompt-eval-harness helm/prompt-eval-harness

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache .coverage prompt_eval.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
