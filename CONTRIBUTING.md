# Contributing

Thanks for helping improve Ruleshelf. It is a small, deliberately boring stack: FastAPI +
SQLite on the server, React + Vite in the browser, one container.

## Getting set up

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```

## Before opening a pull request

```bash
cd backend && pytest -q && ruff check app tests
cd frontend && npm run build
```

- Keep the API typed in `frontend/src/lib/api.ts`.
- Add a test for behaviour changes in `backend/tests/`. Ingestion, filtering and ranking are the
  parts most worth covering.
- UI changes should keep the app usable on a phone-width screen.
- No new runtime dependency unless it earns its place; the image is intentionally small.

## Adding things

- **AI provider dialect** — add `backend/app/providers/<name>.py` and register it at import time.
  If the API matches OpenAI's `/chat/completions` and `/embeddings`, users can already add it as a
  custom provider; no code needed.
- **File format** — add `backend/app/extractors/<name>.py` and call `register_extractor`.
- **Game type / role** — usually just data, add it in the UI. Built-in types are seeded from
  `backend/app/defaults.py`, so changing those affects new installs only.
- **Prompting / ranking** — `backend/app/services/rag.py` and `services/search.py`.

## Database changes

SQLite schema lives in `backend/app/db.py`. Bump `SCHEMA_VERSION` and add an idempotent migration in
`init_db` guarded by the previous version. Do not drop user data. Embeddings can always be rebuilt,
documents can be re-indexed, but uploaded files are irreplaceable.

## Code style

- Python: Ruff (`E`, `F`, `I`), line length 100, type hints on public functions.
- TypeScript: strict mode, no `any` unless unavoidable.
- Comments explain *why*, not *what*.
