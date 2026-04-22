# AI Call QA & Sales Coach MVP

Repository scaffold aligned with `docs/STRUCTURE.md`.

## Quick start

Create a local `.env` file from `.env.example` before starting the stack.

```powershell
Copy-Item .env.example .env
```

Start the Stage 0 stack from the repository root.

```powershell
docker compose up --build
```

Published ports are bound to `127.0.0.1` for local-only access.

Smoke check the API after the stack starts:

- `GET http://127.0.0.1:8000/health`

Example on Windows PowerShell:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/health | Select-Object -ExpandProperty Content
```

## Before Pushing To Git

Check these points before publishing the repository:

- `.env` is not committed
- no real secrets are left in example files or docs
- `storage/audio/`, `data/demo/`, and local cache folders are not staged
- fast local checks pass:

Use `-p no:cacheprovider` for local `pytest` commands in this workspace to avoid Windows cache permission warnings.

```powershell
python -m ruff check apps/app-api/src apps/app-api/tests --no-cache
python -m mypy --python-version 3.12 --ignore-missing-imports apps/app-api/src --no-incremental --cache-dir=nul
python -m pytest apps/app-api/tests -q -p no:cacheprovider
```

- if you changed bootstrap, Docker, Compose, or environment files, also run:

```powershell
docker compose config
docker compose up --build
Invoke-WebRequest -Uri http://127.0.0.1:8000/health | Select-Object -ExpandProperty Content
docker compose exec app-api sh -lc "test -d /app/storage/audio"
docker compose exec db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT extname FROM pg_extension WHERE extname = ''vector''"'
```

GitHub Actions remains the final clean-environment verification for every push and pull request.
