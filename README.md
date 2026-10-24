# Agent Requirement System

Agent is a multi-agent system that turns a natural-language business requirement into a delivery package. It clarifies the requirement, designs a solution, produces a technical design, reviews the result, and exports the files. The web application is branded Agent. The API title is Multi-Agent Requirement Delivery System.

## What it does

- Accepts a requirement and runs it as an asynchronous task.
- Splits the work across planner, solution, engineer, and reviewer roles.
- Pauses for human clarification when too many questions remain open.
- Waits for human approval after review, then exports the deliverables.
- Shows failure reasons, the PRD, the technical design, and the review on the task page.
- Traces every PRD feature by `feature_id` into APIs and tables. Missing coverage is patched incrementally; no placeholder endpoints are generated to inflate the score.

Deliverables are written to `output/<task-id>/`. Task state is stored in SQLite.

Recent additions are documented in [新增功能说明.md](新增功能说明.md): image-based requirement intake (vision model with OCR fallback) and per-call usage accounting with the statistics page.

## Workflow

```text
normalize input → plan → evaluate plan
    → human clarification, when many questions remain
    → solution → engineering → review
    → automatic repair and another review, when review fails
    → human approval → package output
```

During plan evaluation, answer open questions in the clarification box. That step is not final approval. The approve and reject actions appear after review has passed.

The engineer calls an OpenAI-compatible API with structured output. If a response hits the length limit, the same conversation continues and the truncated JSON is repaired. `OPENAI_MAX_TOKENS` sets the size of one completion, default `8192`. `STRUCTURED_OUTPUT_MAX_CONTINUATIONS` sets how many continuation rounds are allowed, default `3`. A very large request can still fail after those rounds. State the goal, core features, and constraints, and avoid asking for a complete codebase in one task.

## Stack

| Part | Implementation |
| --- | --- |
| Agent workflow | LangChain, LangGraph |
| Model API | OpenAI Chat Completions compatible endpoint |
| Backend | FastAPI, Uvicorn, SQLite, SQLAlchemy |
| Frontend | Vue 3, TypeScript, Vite, Element Plus, Pinia |
| Optional memory | ChromaDB, disabled by default |

Layout:

```text
app/                 Backend agents, workflow, API, and settings
frontend-vue/        Vue application
data/                SQLite database and checkpoints
output/              Task deliverables
tests/               Backend tests
.env.example         Environment template
docker-compose.yml   Container compose file
Dockerfile           Backend image
start.bat            Windows launcher
```

## Pages and login

In local development, open `http://127.0.0.1:5173`. Unauthenticated visits go to the login page.

The demo account is checked only in the browser:

- Username: `admin`
- Password: `admin`

The session is stored in `sessionStorage` for the current tab. Closing the tab requires another login. Use **退出** in the header to sign out.

After login, the app provides a dashboard, task creation, task history, and task detail. The create page includes templates for authentication, commerce, education, project management, medical consultation, and finance/tax. A selected template can still be edited.

## Before deployment

Required:

- Python 3.11 or 3.12
- Node.js 20 or newer
- An OpenAI-compatible model endpoint and API key

Docker deployment also needs Docker Engine and Docker Compose. The backend image uses Python 3.11. The frontend build image uses Node.js 24.

From the project root:

```bash
cp .env.example .env
mkdir -p data output
```

Set at least:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_MODEL_NAME=deepseek-chat
```

Replace the base URL and model name with the provider you use. The values above are only an example of a compatible endpoint. Do not commit `.env` or share it.

Other settings:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | Task database | `sqlite+aiosqlite:///./data/tasks.db` |
| `OPENAI_MAX_TOKENS` | Maximum tokens per completion | `8192` |
| `STRUCTURED_OUTPUT_MAX_CONTINUATIONS` | Continuation rounds after a length limit | `3` |
| `MAX_REFLOW_COUNT` | Review reflow limit | `2` |
| `REPAIRER_ENABLED` | Repair after a failed review | `true` |
| `SELF_REFINE_ENABLED` | Reserved; the current version adds no extra self-critique call | `true` |
| `MEMORY_ENABLED` | Vector memory | `false` |
| `DIALOGUE_ENABLED` | Multi-agent dialogue | `false` |
| `PLAN_VARIANTS_ENABLED` | Parallel plan variants | `false` |
| `INPUT_NORMALIZE_LLM_ENABLED` | Use the model for input cleanup; `false` uses rule-based cleanup and saves one call | `false` |
| `INPUT_NORMALIZE_MAX_CHARS` | Truncation limit for normalized input | `8000` |
| `TASK_WORKER_CONCURRENCY` | Tasks executed in parallel | `2` |
| `CONTINUATION_SLIM_CONTEXT_ENABLED` | Send only the tail on later continuation rounds | `true` |
| `LANGCHAIN_TRACING_V2` | LangSmith tracing | `false` |

Cost notes: with memory disabled, no Chroma client is opened. The engineer makes one full design call and up to two small patch calls for missing features; it no longer regenerates the whole design per round. The reviewer no longer performs a second full review when rules override the model's conclusion.

Restart the backend after changing `.env`. The model client caches settings, so saving the file alone does not apply them.

## Model routing

Each agent role can use a different model, provider endpoint, and key. Empty role values inherit the global `OPENAI_*` settings.

```dotenv
MODEL_ROUTING_ENABLED=true
MODEL_ROUTING_FALLBACK_ENABLED=true

# Planner on a reasoning model through a relay
ROLE_PLANNER_MODEL=gpt-6.1-sol
ROLE_PLANNER_API_BASE=https://api.example.com/v1
ROLE_PLANNER_API_KEY=sk-...
ROLE_PLANNER_REASONING_EFFORT=high

# Engineering and review on a cheaper model
ROLE_ENGINEER_MODEL=deepseek-flash
ROLE_REVIEWER_MODEL=deepseek-flash
```

Supported roles: `planner`, `solution`, `engineer`, `reviewer`, `repairer`, `evaluator`, `dialogue`, `normalizer`. Each accepts `_MODEL`, `_API_BASE`, `_API_KEY`, `_MAX_TOKENS`, and `_REASONING_EFFORT`.

Routing can also be edited at **模型配置** (`/settings`) in the UI. Saved values go to `data/model_routing.json`, take precedence over `.env`, and apply without a restart. The file stores API keys in plaintext; `data/` is excluded by `.gitignore`.

If a role model fails, the call is retried once on the global model, including continuation rounds. Token usage is recorded per node, per role, and per model, then converted to CNY with `MODEL_PRICING_JSON` and `USD_TO_CNY_RATE`. Built-in prices use off-peak DeepSeek rates and standard OpenAI rates; override them in `MODEL_PRICING_JSON` when they change.

```dotenv
MODEL_PRICING_JSON={"deepseek-flash":{"input":1.5,"cached_input":0.05,"output":4.5,"currency":"CNY"}}
```

DeepSeek bills in CNY with **two time-of-day tiers**: a peak rate on weekdays 09:00–12:00 and 14:00–18:00 (Beijing time), and half that rate at all other times, including weekends and public holidays. The built-in table stores the peak rate (`deepseek-flash`: 2 / 0.04 / 8 per 1M tokens for input, cached input, and output; `deepseek-v4-pro`: 9 / 0.3 / 27). Every usage row is stamped with whether it happened during peak hours, and off-peak rows are charged at `OFF_PEAK_PRICE_RATIO` (default `0.5`).

DeepSeek prices are no longer scraped. The earlier scraper read the CNY table and labelled it USD, then multiplied by the exchange rate, dropping the peak multiplier — which is why the totals did not match the official bill. OpenAI models still sync from the LiteLLM price table (openai.com blocks server-side requests).

Prices are not exposed anywhere in the product. The rate table still exists internally (`data/model_pricing.json` overrides the built-in defaults) and is used only to fill the `cost_cny` column of `llm_usage`; no feature reads that column. `POST /stats/usage/recost` rewrites it for all rows using whatever table is currently loaded.

A task that failed review can be re-run from the engineering stage without regenerating the PRD: open the task and click **二次优化**. When the previous technical design exists it enters at `repairer` (fills only missing coverage), otherwise it falls back to a full `engineer` rebuild.

Rejecting at the approval step resets `reflow_count` and `repair_attempted`, so the rebuilt version regains its automatic repair rounds instead of going straight back to approval.

The reviewer re-checks the previous round's issues before scoring: it must mark each as resolved or unresolved, and resolved items are not reported again. This keeps the issue list converging across repair rounds instead of surfacing a new random set each time.

A task that failed while calling a model can be resumed in place with **重试任务**: it re-enters at the failing node, so completed stages are not re-run. Failures are classified (billing, auth, rate limit, timeout, network) and shown with an actionable hint instead of a raw provider payload.

The overall score is exactly the rubric-weighted value; it is never clamped by loose full-text PRD coverage. Issues are tagged `origin: new | carried` so a re-review distinguishes freshly found problems from previously reported ones still open. The delivery package sits at the top of the task page.

## Usage ledger

Token figures come from a dedicated `llm_usage` table — **one row per model call** — not from task snapshots.

That distinction matters. A node writes its output to the database only when it finishes; a node that raises after spending 200k tokens leaves no snapshot entry, so a snapshot-based total silently under-reports real spending. Writing at call time keeps failed tasks, interrupted runs, continuation rounds, and image extraction in the same ledger.

| Property | Behaviour |
| --- | --- |
| Granularity | One row per call: task, node, role, model, prompt, completion, cached, peak/off-peak, cost |
| Failure path | Rows are written in the LLM callback, so a node that throws still gets counted |
| Image extraction | The vision channel writes `source=vision` rows with its own token usage |
| History | On startup, tasks that only have snapshot totals are backfilled once (idempotent) |
| Reconciliation | `GET /stats/usage` returns totals, daily series, and breakdowns by model / role / node / source |

Historical rows that were never captured cannot be reconstructed — the tokens were spent, but no record survived. Figures become exact for every run started after this change.

**Pricing is disabled.** No screen shows money, and there is no cost cap — the settings page only configures model routing. Each `llm_usage` row still carries a `cost_cny` value computed from the built-in rate table, kept as an internal record only; nothing reads it. If you need costs later, the data is there; to recompute it, call `POST /stats/usage/recost`.

```bash
curl -X POST http://127.0.0.1:8000/stats/usage/recost      # rewrite llm_usage costs
curl -X POST http://127.0.0.1:8000/stats/usage/backfill    # re-run history backfill
```

## Local deployment

Run these commands from the project root unless noted.

### 1. Backend dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, a Conda environment named `multi_agent_v1` can be used before `pip install -r requirements.txt`.

### 2. Frontend dependencies

```bash
cd frontend-vue
npm ci
```

If the lockfile does not match `package.json`, `npm ci` fails. In that case run `npm install` inside `frontend-vue`.

### 3. Start

Terminal 1, from the project root:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Terminal 2:

```bash
cd frontend-vue
npm run dev -- --host 0.0.0.0 --port 5173
```

On Windows, run `start.bat backend` and `start.bat frontend` from the project root.

### 4. Check

- Application: <http://127.0.0.1:5173>
- API docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>, which returns `{"status":"ok"}`

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` and strips the `/api` prefix. Start the backend before using the UI.

## Docker deployment

Create `.env` in the project root, then run:

```bash
docker compose up --build
```

On Windows, the matching command is `start.bat docker`.

After startup:

- Application: <http://127.0.0.1:8080>
- API: <http://127.0.0.1:8000>
- Health: <http://127.0.0.1:8000/health>

Nginx serves the built frontend. Browser requests to `/api` are forwarded to the `api:8000` service. The `data/` and `output/` directories are mounted from the host, so tasks and deliverables remain in the project directory.

Stop the stack:

```bash
docker compose down
```

## Image requirement extraction

The create page accepts images in addition to text: requirement screenshots, chat logs, whiteboard photos, or handwritten notes. Extraction runs on two channels and degrades automatically.

```text
upload → validate/preprocess → vision model (when configured)
                              ↘ not configured / failed / timeout → local OCR
                             → clean & structure → editable text → user applies it
```

| Channel | Requirement | Behaviour |
| --- | --- | --- |
| Vision model | `vision` role configured at **模型配置** | Preferred. One call returns goal, features, constraints, and the transcript |
| Local OCR | None — installed with the backend | Fallback. RapidOCR on ONNX Runtime, CPU only, runs offline |

Stability rules:

- The upload is handled in memory and never written to disk.
- Validation happens twice: byte size (default 10MB) and a real decode with Pillow. Unsupported formats, truncated files, and images above 40 megapixels are rejected before any model sees them.
- Images are EXIF-rotated, converted to RGB, and resized to a 2000px long edge before recognition.
- The OCR engine is a lazily loaded process singleton, executed in a thread pool with a concurrency limit of 2 and a 30s timeout, so a large upload cannot block the event loop.
- Vision calls time out at 60s and retry once on 429/5xx. Any failure falls back to OCR.
- Recognition failures return HTTP 200 with a warning instead of an error, so the page never deadlocks. Only invalid requests return 4xx (`400 not_image`, `400 corrupt`, `413 too_large`).
- The extracted text is always editable, and nothing is submitted to the workflow until you press a fill button and then **提交需求**.

Configure the vision channel either in `.env` or at **模型配置 → 图片识别（多模态）**. Any OpenAI-compatible endpoint that accepts `image_url` content works:

```dotenv
ROLE_VISION_MODEL=qwen-vl-max
ROLE_VISION_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
ROLE_VISION_API_KEY=sk-...
```

Leaving the role empty inherits the global model, which works as long as that model accepts images (for example `deepseek-flash`). If the resolved model cannot read images, the call fails fast and the request falls back to local OCR. Check the current state with `GET /extract/status`, or run `python scripts/check_ocr.py` to verify the OCR engine on a generated sample.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/tasks` | Create a task with `{"user_input":"..."}` |
| `GET` | `/tasks` | List tasks |
| `GET` | `/tasks/{task_id}` | Read task status |
| `POST` | `/tasks/{task_id}/feedback` | Submit clarification or approval |
| `GET` | `/tasks/{task_id}/result` | Read the deliverable |
| `GET` | `/tasks/{task_id}/stream` | Server-sent progress events |
| `GET` | `/extract/status` | Available extraction channels and limits |
| `POST` | `/extract/image` | Upload an image (`multipart/form-data`, field `file`) and extract requirement text |

The login page protects frontend routes only. These API endpoints do not check the demo account.

## Tests

With the virtual environment active, from the project root:

```bash
pytest tests -v
```

## Suggested use

1. Sign in with `admin` / `admin`.
2. Pick a template or write the requirement, including the goal, core features, and constraints.
3. When the task is waiting for clarification, answer in the clarification area and submit.
4. After review passes, approve the result. Rejection sends the task back to solution design.
5. Read the documents on the task page, or open `output/<task-id>/`.
6. If a task fails, the detail page shows the failed step and the reason. Narrow the requirement and create a new task.
