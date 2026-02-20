## 1) Environment setup

From repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Create your env file:

```bash
cp .env.example .env
```

Set required values in `.env`:

- `ANTHROPIC_API_KEY` (required)
- `GITHUB_TOKEN` (required for branch/PR operations)

Optional/common:

- `USE_MODAL=true` (default behavior in config)
- `DATABASE_URL=sqlite+aiosqlite:///./ramp_agent.db`
- `ARTIFACTS_DIR=./artifacts`

If you want local sandbox instead of Modal, set:

```dotenv
USE_MODAL=false
```

## 2) Run backend

From repo root (with venv active):

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Checks:

- Health: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

## 3) Run frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

- `http://127.0.0.1:5173`
