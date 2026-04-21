# AI Call QA & Sales Coach MVP

Repository scaffold aligned with `docs/STRUCTURE.md`.

## Quick start

Create a local `.env` file from `.env.example` before starting the stack.

```bash
docker compose up --build
```

Published ports are bound to `127.0.0.1` for local-only access.

Health check:

- `GET http://127.0.0.1:8000/health`

## Before Pushing To Git

Check these points before publishing the repository:

- `.env` is not committed
- no real secrets are left in example files or docs
- `storage/audio/`, `data/demo/`, and local cache folders are not staged
- `docker compose config` passes
- optional: `docker compose up --build` and `GET /health` pass locally
