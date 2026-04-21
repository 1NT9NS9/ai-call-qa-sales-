# Repository Structure Specification

## Purpose

This document defines the required repository layout for the MVP described in [PLAN.md](PLAN.md).
It specifies repository-level structure only.

System design is defined in [ARCHITECTURE.md](ARCHITECTURE.md).
Contract definitions are defined in [CONTRACTS.md](CONTRACTS.md).
External integration boundaries are defined in [INTEGRATIONS.md](INTEGRATIONS.md).
Security rules are defined in [SECURITY.md](SECURITY.md).
Scaling boundaries are defined in [SCALING.md](SCALING.md).
Stage sequencing and completion criteria are defined in [stages/README.md](stages/README.md).

## Required Repository Layout

```text
/
|-- .github/
|   |-- workflows/
|   |   `-- ci.yml
|
|-- README.md
|-- .env
|-- .env.example
|-- .gitignore
|-- .dockerignore
|-- docker-compose.yml
|
|-- docs/
|   |-- ARCHITECTURE.md
|   |-- CONTRACTS.md
|   |-- INTEGRATIONS.md
|   |-- PLAN.md
|   |-- SCALING.md
|   |-- SECURITY.md
|   |-- STRUCTURE.md
|   `-- stages/
|       |-- README.md
|       |-- stage-0-setup.md
|       |-- stage-1-database.md
|       |-- stage-2-transcription.md
|       |-- stage-3-rag.md
|       |-- stage-4-analysis.md
|       `-- stage-5-export.md
|
|-- storage/
|   `-- audio/
|
|-- data/
|   |-- kb_seed/
|   `-- demo/
|
`-- apps/
    `-- app-api/
        |-- Dockerfile
        |-- requirements.txt
        |-- alembic.ini
        |-- alembic/
        |   `-- versions/
        |-- src/
        |   |-- main.py
        |   |-- api/
        |   |-- application/
        |   |-- domain/
        |   |-- infrastructure/
        |   |-- adapters/
        |   |-- resources/
        |   `-- config/
        `-- tests/
```

## Directory Responsibilities

### Root

- `.github/` shall contain GitHub workflow files.
- `README.md` shall contain local startup instructions.
- `.env` may exist as a local runtime file and shall remain git-ignored.
- `.env.example` shall define required runtime configuration keys.
- `docker-compose.yml` shall start the backend and database for local development.
- `docs/` shall contain project documentation only.

### Documentation

- [PLAN.md](PLAN.md) is the implementation plan and document index.
- [ARCHITECTURE.md](ARCHITECTURE.md) defines system structure and runtime flow.
- [CONTRACTS.md](CONTRACTS.md) defines lifecycle, object, and analysis contracts.
- [INTEGRATIONS.md](INTEGRATIONS.md) defines external integration boundaries and interface contracts.
- [SCALING.md](SCALING.md) defines MVP scaling boundaries and the post-MVP evolution path.
- [STRUCTURE.md](STRUCTURE.md) defines repository layout and directory responsibilities.
- [SECURITY.md](SECURITY.md) defines the MVP security baseline.
- [stages/README.md](stages/README.md) contains stage-specific completion and handoff criteria.

### Data And Storage

- `storage/audio/` shall contain uploaded audio files or mounted storage content.
- `data/kb_seed/` shall contain seed knowledge base documents used for retrieval testing.
- `data/demo/` shall contain demo assets and example scenarios.

### Application

- `apps/app-api/src/api/` shall contain HTTP routes, request schemas, and API dependencies.
- `apps/app-api/src/application/` shall contain use cases, orchestration logic, and application services.
- `apps/app-api/src/domain/` shall contain domain entities, interfaces, enums, and business rules.
- `apps/app-api/src/infrastructure/` shall contain database access, storage integration, and logging setup.
- `apps/app-api/src/adapters/` shall contain external provider integrations behind internal interfaces.
- `apps/app-api/src/resources/` shall contain prompts, schemas, and rubric definitions.
- `apps/app-api/src/config/` shall contain runtime configuration loading.
- `apps/app-api/tests/` shall contain unit and integration tests.
