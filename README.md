# Prompt Eval Harness

A CLI + web UI for testing, evaluating, and versioning LLM prompts across multiple model
providers. Built to tune prompts for AI agents running in a homelab Kubernetes cluster, but
general-purpose enough for any prompt-engineering workflow: author a prompt, define a suite
of test cases, run it against OpenAI, Anthropic, and Google Gemini side by side, and score the
results automatically.

## Features

- **Prompt template management** — Jinja2-templated prompts with automatic variable
  extraction and validation.
- **Version history** — every edit creates a new immutable version; diff any two versions
  with a unified-diff view.
- **Test case suites** — group input/expected-output pairs, each with its own evaluation
  strategy and criteria.
- **Multi-model comparison** — run the same prompt version against any combination of
  registered model configs (OpenAI, Anthropic, Google Gemini) in a single batch run.
- **Pluggable evaluation methods**:
  - `exact_match` — normalized string equality (case/whitespace configurable)
  - `semantic_similarity` — dependency-free similarity ratio against a threshold
  - `llm_as_judge` — an LLM scores the output 0–100 against a rubric
- **Async batch runs** — evaluation runs execute on a Celery worker; watch progress live
  over a WebSocket or poll the REST API.
- **Export** — download a run's results as JSON or CSV.

## Architecture

```
                         ┌─────────────────────┐
                         │       Browser         │
                         │   (Web UI, REST/WS)   │
                         └──────────┬────────────┘
                                    │ HTTP / WebSocket
                                    ▼
┌───────────────────────────────────────────────────────────┐
│                        FastAPI app                          │
│  routers: prompts · test-suites · model-configs · runs      │
│  services: templater (Jinja2) · evaluator · llm_client       │
└───────────┬───────────────────────────────┬────────────────┘
            │ SQLAlchemy                     │ enqueue task
            ▼                                ▼
   ┌─────────────────┐             ┌───────────────────┐
   │      SQLite       │             │  Redis (broker +   │
   │  prompts, suites,  │             │  result backend)   │
   │  runs, results      │             └─────────┬──────────┘
   └─────────────────┘                           │
                                                  ▼
                                     ┌────────────────────────┐
                                     │     Celery worker        │
                                     │  renders prompt → calls  │
                                     │  provider → scores →     │
                                     │  persists EvalResult      │
                                     └────────────┬─────────────┘
                                                  │
                              ┌───────────────────┼───────────────────┐
                              ▼                   ▼                   ▼
                         OpenAI API         Anthropic API        Google Gemini API
```

## Tech Stack

| Layer            | Choice                                   |
|-------------------|-------------------------------------------|
| API               | FastAPI, Pydantic v2                       |
| Async workers      | Celery + Redis                             |
| Database           | SQLite (SQLAlchemy 2.0 + Alembic-ready)    |
| Templating         | Jinja2 (sandboxed environment)             |
| LLM providers      | OpenAI, Anthropic, Google Generative AI    |
| Testing            | Pytest, pytest-asyncio, pytest-cov         |
| Packaging          | Docker, Helm                               |

## API Endpoints

All endpoints are mounted under `/api`.

| Method | Path                                          | Description                                     |
|--------|------------------------------------------------|--------------------------------------------------|
| GET    | `/health`                                      | Liveness/readiness probe                          |
| GET    | `/api/prompts`                                 | List prompts                                       |
| POST   | `/api/prompts`                                 | Create a prompt (and its first version)            |
| GET    | `/api/prompts/{id}`                            | Get a prompt with full version history              |
| DELETE | `/api/prompts/{id}`                            | Delete a prompt                                     |
| POST   | `/api/prompts/{id}/versions`                   | Add a new version to a prompt                        |
| GET    | `/api/prompts/{id}/versions`                   | List a prompt's versions                             |
| GET    | `/api/prompts/{id}/diff`                       | Unified diff between two versions                      |
| GET    | `/api/test-suites`                             | List test suites                                     |
| POST   | `/api/test-suites`                             | Create a test suite                                   |
| GET    | `/api/test-suites/{id}`                        | Get a suite with its test cases                        |
| DELETE | `/api/test-suites/{id}`                        | Delete a suite                                        |
| POST   | `/api/test-suites/{id}/test-cases`             | Add a test case to a suite                              |
| GET    | `/api/test-suites/{id}/test-cases`             | List a suite's test cases                              |
| DELETE | `/api/test-suites/{id}/test-cases/{case_id}`   | Delete a test case                                     |
| GET    | `/api/model-configs`                           | List model configs                                     |
| POST   | `/api/model-configs`                           | Register a model config (provider + model id + params)  |
| GET    | `/api/model-configs/{id}`                      | Get a model config                                      |
| DELETE | `/api/model-configs/{id}`                      | Delete a model config                                    |
| POST   | `/api/runs`                                    | Launch a batch evaluation run                             |
| GET    | `/api/runs`                                    | List runs                                                |
| GET    | `/api/runs/{id}`                               | Get a run with all per-test-case results                   |
| GET    | `/api/runs/{id}/summary`                       | Pass rate / average score, broken down by model              |
| GET    | `/api/runs/{id}/export`                        | Export results as JSON or CSV (`?format=`)                    |
| WS     | `/api/runs/{id}/ws`                            | Live run status updates                                        |

Interactive API docs are available at `/docs` (Swagger UI) and `/redoc` while the app is running.

## Quickstart (local development)

Requires Python 3.11+ and a local Redis instance.

```bash
make install                     # create .venv and install the package with dev extras
redis-server &                   # or run Redis via Docker

cp .env.example .env              # add any provider API keys you plan to use
make run                          # starts FastAPI on http://localhost:8000 with autoreload

# in a second terminal
make worker                       # starts the Celery worker that executes batch runs
```

Run the test suite:

```bash
make test
```

## Quickstart (Docker Compose)

```bash
docker compose up --build
```

This starts three services: `redis`, `api` (FastAPI on `:8000`), and `worker` (Celery). Set
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GOOGLE_API_KEY` in your shell or a `.env` file
before starting — they're passed through to both `api` and `worker`.

## Deploying to Kubernetes

A Helm chart is provided at `helm/prompt-eval-harness/`.

1. **Build and push the image**:

   ```bash
   docker build -t <your-registry>/prompt-eval-harness:0.1.0 .
   docker push <your-registry>/prompt-eval-harness:0.1.0
   ```

2. **Install or upgrade the release**:

   ```bash
   helm upgrade --install prompt-eval-harness helm/prompt-eval-harness \
     --set image.repository=<your-registry>/prompt-eval-harness \
     --set image.tag=0.1.0 \
     --set ingress.host=prompt-eval.yourdomain.com \
     --set secrets.openaiApiKey=$OPENAI_API_KEY \
     --set secrets.anthropicApiKey=$ANTHROPIC_API_KEY \
     --set secrets.googleApiKey=$GOOGLE_API_KEY
   ```

   Or use the Makefile shortcut (edit `values.yaml` first, or pass `--set` flags via
   `HELM_ARGS`):

   ```bash
   make helm-install
   ```

3. **What gets deployed**: a `Deployment` (2 replicas by default), a `ClusterIP` `Service`,
   an `Ingress` with a configurable hostname, a `ConfigMap` for non-secret settings
   (`ENVIRONMENT`, `DATABASE_URL`, `REDIS_URL`, `CORS_ORIGINS`, `DEFAULT_JUDGE_MODEL`), and a
   `Secret` for the three provider API keys. Redis and the Celery worker are expected to run
   as their own releases/Deployments in the same namespace — point `env.redisUrl` at
   whichever Redis service you deploy alongside this chart.

4. **Key values** (see `values.yaml` for the full list):

   | Value                    | Purpose                                    |
   |----------------------------|-----------------------------------------------|
   | `replicaCount`             | Number of API pod replicas                       |
   | `image.repository` / `tag` | Container image to deploy                          |
   | `service.port`              | Port the `Service` exposes                          |
   | `ingress.host`               | Public hostname routed to the service                |
   | `ingress.tls.enabled`         | Toggle TLS termination at the ingress                 |
   | `resources`                    | CPU/memory requests and limits                          |
   | `env.*`                          | Non-secret config injected via `ConfigMap`               |
   | `secrets.*`                        | Provider API keys injected via `Secret`                     |

## Project Layout

```
prompt-eval-harness/
├── src/prompt_eval/
│   ├── main.py            FastAPI app entrypoint
│   ├── config.py           Settings via environment variables
│   ├── models.py            SQLAlchemy ORM models
│   ├── schemas.py            Pydantic request/response schemas
│   ├── database.py            Engine, session factory, init_db
│   ├── routers/                 prompts, tests, models, runs
│   ├── services/                  evaluator, llm_client, templater
│   └── workers/                     celery_app (batch evaluation task)
├── tests/                            pytest suite (mirrors src/ structure)
├── helm/prompt-eval-harness/          Helm chart for k8s deployment
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

## Configuration

All configuration is sourced from environment variables (see `src/prompt_eval/config.py`),
optionally via a local `.env` file. No secrets are ever hardcoded.

| Variable                | Default                              | Purpose                              |
|---------------------------|-----------------------------------------|------------------------------------------|
| `DATABASE_URL`             | `sqlite:///./prompt_eval.db`             | SQLAlchemy connection string                |
| `REDIS_URL`                  | `redis://localhost:6379/0`                | Redis instance backing Celery                 |
| `OPENAI_API_KEY`               | _(unset)_                                    | Required to run OpenAI model configs             |
| `ANTHROPIC_API_KEY`               | _(unset)_                                    | Required to run Anthropic model configs             |
| `GOOGLE_API_KEY`                     | _(unset)_                                    | Required to run Google Gemini model configs           |
| `CORS_ORIGINS`                         | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed origins for the frontend |
| `DEFAULT_JUDGE_MODEL`                     | `gpt-4o-mini`                                | Default model id for `llm_as_judge` evaluations    |

## License

MIT
