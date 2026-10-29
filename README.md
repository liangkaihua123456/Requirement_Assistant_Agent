# Agent Requirement System

Agent is a multi-agent system that turns a natural-language business requirement into a delivery package. It clarifies the requirement, designs a solution, produces a technical design, reviews the result, and exports the files. The web application is branded Agent. The API title is Multi-Agent Requirement Delivery System.

## What it does

- Accepts a requirement and runs it as an asynchronous task.
- Splits the work across planner, solution, engineer, and reviewer roles.
- Pauses for human clarification when too many questions remain open.
- Waits for human approval after review, then exports the deliverables.
- Shows failure reasons, the PRD, the technical design, and the review on the task page.

Deliverables are written to `output/<task-id>/`. Task state is stored in SQLite.

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
| `SELF_REFINE_ENABLED` | Self-check of generated output | `true` |
| `MEMORY_ENABLED` | Vector memory | `false` |
| `DIALOGUE_ENABLED` | Multi-agent dialogue | `false` |
| `PLAN_VARIANTS_ENABLED` | Parallel plan variants | `false` |
| `LANGCHAIN_TRACING_V2` | LangSmith tracing | `false` |

Restart the backend after changing `.env`. The model client caches settings, so saving the file alone does not apply them.

### DingTalk robot (optional)

The backend can run a DingTalk Stream-mode robot inside the FastAPI process. It
creates tasks from group messages, posts clarification/review prompts, accepts
feedback in the group, and notifies on completion or failure.

```dotenv
DINGTALK_SERVICE_ENABLED=true
DINGTALK_APP_KEY=your-client-id
DINGTALK_APP_SECRET=your-client-secret
# optional
DINGTALK_NOTIFY_INTERVAL_SECONDS=3
```

The app must be an internal DingTalk application with a robot, Stream mode
enabled, and the robot added to the test group. The secret is read from `.env`
only; do not commit it.

Operational notes:

- Run a single uvicorn worker. The service uses a `flock` leader lock so only
  one worker opens the DingTalk WebSocket; other workers keep serving the API.
- Bindings and `msgId` dedup live in `dingtalk_bindings` / `dingtalk_messages`
  in the task database, so they survive restarts.
- Group commands: any text creates a task, `状态` / `status` queries the current
  task, `通过` approves, and `驳回 <reason>` rejects. Only the original requester
  can answer a clarification or approve a review.
- One active task per conversation is enforced by a partial unique index.
- Notifications use the message `sessionWebhook`, which expires. For long tasks,
  add an OpenAPI fallback before relying on completion pushes in production.

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
