# Tasks for Stage 0

## Assumptions
- The task list is scoped only to [docs/PLAN.md](/C:/IT/project/hr_project_05/docs/PLAN.md) and [docs/stages/stage-0-setup.md](/C:/IT/project/hr_project_05/docs/stages/stage-0-setup.md).
- Stage 0 includes explicit local bootstrap for PostgreSQL and `pgvector`, but does not include any business-domain models, persistence flows, STT, RAG, analysis, or outbound delivery.
- "Connect PostgreSQL" means the backend runtime is configured against the Compose database service and that this configuration is exercised by a bounded bootstrap check.
- "Enable `pgvector`" means the local database bootstrap creates or confirms the `vector` extension explicitly; using a `pgvector`-capable image alone is not sufficient.
- Verification is performed on Windows with Docker Compose available locally.

## Task List

### T1. Bootstrap the FastAPI app and `/health`
- Estimate: 1-2h
- Goal: Create the minimal backend entrypoint required for local runtime verification.
- Do:
  - Add or confirm a minimal `FastAPI` application entrypoint.
  - Add `GET /health` with a simple success response.
  - Keep the endpoint independent of business logic and later-stage integrations.
- Result:
  - The backend can start as a web service and exposes `GET /health`.
- Verification:
  - Start the app locally or in the container.
  - Confirm `GET /health` returns HTTP 200 with the expected success payload.
- Depends on:
  - None.

### T2. Define the backend bootstrap configuration
- Estimate: 1-2h
- Goal: Make the Stage 0 runtime contract explicit for the app process.
- Do:
  - Add or confirm minimal runtime configuration loading for app environment, port, `DATABASE_URL`, and audio storage path.
  - Add or confirm `.env.example` with the minimal Stage 0 keys required by the app and Compose.
  - Ensure the backend is wired to the Compose PostgreSQL service through configuration, not hardcoded values in service logic.
  - Keep configuration limited to Stage 0 bootstrap needs.
- Result:
  - The backend has a clear bootstrap configuration contract for local startup.
- Verification:
  - The app can resolve all required Stage 0 configuration values from environment variables.
  - `.env.example` contains every Stage 0 variable referenced by the app bootstrap and Compose setup.
  - `DATABASE_URL` points to the Compose database service and is used by the backend bootstrap path.
- Depends on:
  - T1.

### T3. Define the backend container image
- Estimate: 1-2h
- Goal: Make the API service runnable in Docker without manual container setup.
- Do:
  - Add or confirm `apps/app-api/Dockerfile`.
  - Install only bootstrap dependencies from `requirements.txt`.
  - Copy the app source into the image.
  - Expose the API port and define the runtime command for the FastAPI service.
- Result:
  - A reproducible backend container definition exists for local development.
- Verification:
  - `docker compose build app-api` succeeds.
  - The backend container can start its process from the image.
- Depends on:
  - T1, T2.

### T4. Define the local Compose stack and database readiness
- Estimate: 1-2h
- Goal: Start the backend and PostgreSQL together from the repo root with bounded readiness behavior.
- Do:
  - Add or confirm `docker-compose.yml` with `app-api` and `db` services.
  - Use a PostgreSQL image with `pgvector` support.
  - Wire environment loading, local-only published ports, and service startup order.
  - Add a bounded database readiness check so the backend does not race the database bootstrap.
- Result:
  - The repository has a local stack definition for backend plus database with startup coordination.
- Verification:
  - `docker compose up` starts backend and database without manual edits.
  - The database reaches a healthy/ready state before the backend bootstrap depends on it.
- Depends on:
  - T2, T3.

### T5. Enable `pgvector` for the local database bootstrap
- Estimate: 1-2h
- Goal: Make `pgvector` enablement an explicit Stage 0 bootstrap outcome.
- Do:
  - Add a concrete local bootstrap step that creates or confirms the `vector` extension.
  - Keep the mechanism idempotent so repeated local startup does not require manual repair.
  - Limit the work to extension enablement only; do not introduce schema or application models.
- Result:
  - The local database has `pgvector` explicitly enabled for later stages.
- Verification:
  - A bounded check confirms the `vector` extension exists in the running local database.
- Depends on:
  - T2, T4.

### T6. Configure mounted audio storage for the backend
- Estimate: 1-2h
- Goal: Provide the mounted storage path required by the stage without introducing upload logic.
- Do:
  - Add or confirm the `storage/audio` host directory.
  - Mount it into the backend container through Compose.
  - Align the mount target with the configured storage path used by the backend bootstrap.
- Result:
  - The backend runtime has access to a mounted local audio storage directory.
- Verification:
  - With the stack running, the backend container can see the configured audio directory at the expected path.
- Depends on:
  - T2, T4.

### T7. Document the Stage 0 local startup flow
- Estimate: 1-2h
- Goal: Provide minimal operator instructions for repeatable local bootstrap.
- Do:
  - Add or confirm `README.md` instructions for creating `.env` from `.env.example`.
  - Document how to start the stack and how to call `GET /health`.
  - Keep the documentation limited to Stage 0 local startup and smoke-check steps.
- Result:
  - Local startup instructions exist and match the actual Stage 0 bootstrap flow.
- Verification:
  - A developer can follow `README.md` without guessing missing bootstrap steps.
- Depends on:
  - T3, T4, T5, T6.

### T8. Run the bounded Stage 0 smoke check
- Estimate: 1-2h
- Goal: Validate the full Stage 0 bootstrap path against the documented exit criteria.
- Do:
  - Run `docker compose config`.
  - Run `docker compose up --build`.
  - Check backend startup, database startup, `GET /health`, audio-storage mount visibility, and explicit `pgvector` enablement.
  - Fix only Stage 0 bootstrap defects discovered during this bounded validation pass.
- Result:
  - Stage 0 bootstrap has a concrete, verified end-to-end validation result.
- Verification:
  - `docker compose up --build` starts backend and database without manual fixes.
  - The backend process starts successfully.
  - The database process starts successfully.
  - `GET /health` returns success.
  - The mounted audio storage path is available inside the backend container.
  - The local database confirms `pgvector` is enabled.
- Depends on:
  - T4, T5, T6, T7.

## Exit Criteria Coverage
- `docker compose up` starts the backend and database without manual fixes -> T3, T4, T8
- the backend process starts successfully -> T1, T3, T8
- the database process starts successfully -> T4, T8
- `GET /health` returns a successful response -> T1, T8
- mounted audio storage is configured and available to the backend -> T2, T6, T8
- `.env.example` contains the required local configuration keys -> T2
- in-scope `connect PostgreSQL` bootstrap is covered explicitly -> T2, T4, T8
- in-scope `enable pgvector` bootstrap is covered explicitly -> T5, T8

## Risks / Ambiguities
- The stage document does not define whether PostgreSQL connectivity must be validated during app startup or only documented and wired. This task list assumes a bounded bootstrap check is required.
- The stage document does not define whether audio storage availability requires only mount visibility or an actual write/read check. This task list uses mount visibility at the configured path as the minimum Stage 0 verification.
- If a developer already has persisted local Docker volumes from an older setup, `pgvector` enablement must remain idempotent so Stage 0 verification does not depend on a clean volume.
- No oversized tasks remain if T8 is kept limited to one bounded smoke-check and remediation pass for Stage 0 defects only.

## Proposed Execution Order
1. T1. Bootstrap the FastAPI app and `/health`
2. T2. Define the backend bootstrap configuration
3. T3. Define the backend container image
4. T4. Define the local Compose stack and database readiness
5. T5. Enable `pgvector` for the local database bootstrap
6. T6. Configure mounted audio storage for the backend
7. T7. Document the Stage 0 local startup flow
8. T8. Run the bounded Stage 0 smoke check
