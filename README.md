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

## Stage 5 usage

The Stage 5 API exposes the persisted result through `GET /calls/{call_id}` and delivers the same result through `POST /calls/{call_id}/export`.

### 1. Configure a local webhook target

Add a webhook target to `.env` and restart `app-api` so the container picks up the new value.

```powershell
Add-Content .env 'WEBHOOK_TARGET_URL=http://host.docker.internal:9000/demo-webhook'
docker compose up -d --build app-api
```

Start a simple local receiver in a separate PowerShell window and leave it running while you test export:

```powershell
@'
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        print(body, flush=True)
        self.send_response(202)
        self.end_headers()

    def log_message(self, format, *args):
        return

HTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
'@ | python -
```

### 2. Seed one analyzed sample run

Run this once from the repository root. It creates one analyzed call and prints the new `call_id`.

```powershell
$callId = @'
from src.main import create_app
from src.infrastructure.persistence.models import (
    CallAnalysis,
    CallProcessingStatus,
    CallSession,
    TranscriptSegment,
)

app = create_app()
with app.state.session_factory() as session:
    call = CallSession(
        external_call_id="demo-stage5-call",
        processing_status=CallProcessingStatus.ANALYZED,
        source_type="demo",
        metadata_json={"campaign": "stage5", "channel": "sales"},
    )
    session.add(call)
    session.flush()

    session.add_all(
        [
            TranscriptSegment(
                call_id=call.id,
                speaker="customer",
                text="Pricing feels high for our team.",
                start_ms=0,
                end_ms=1200,
                sequence_no=1,
            ),
            TranscriptSegment(
                call_id=call.id,
                speaker="agent",
                text="I can send ROI proof and next steps today.",
                start_ms=1200,
                end_ms=2400,
                sequence_no=2,
            ),
        ]
    )
    session.add(
        CallAnalysis(
            call_id=call.id,
            result_json={
                "summary": "Customer raised pricing concerns and requested follow-up material.",
                "score": 8.8,
                "score_breakdown": [
                    {
                        "criterion": "Discovery",
                        "score": 4.4,
                        "max_score": 5.0,
                        "reason": "The rep identified the pricing blocker clearly.",
                    }
                ],
                "objections": [
                    {
                        "text": "Pricing feels high.",
                        "handled": True,
                        "evidence_segment_ids": [1],
                    }
                ],
                "risks": [],
                "next_best_action": "Send ROI proof and a mutual action plan.",
                "coach_feedback": "Keep tying price to rollout value.",
                "used_knowledge": [],
                "confidence": 0.91,
                "needs_review": False,
                "review_reasons": [],
            },
            confidence=0.91,
            review_required=False,
            review_reasons=[],
        )
    )
    session.commit()
    print(call.id)
'@ | docker compose exec -T app-api python -
```

### 3. Retrieve the result through the API

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/calls/$callId"
```

The response includes the final result under `result`.

### 4. Trigger webhook export

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/calls/$callId/export"
```

The export response includes `result_id`, `status`, `delivered_at`, and the configured `target_url`.

### 5. Observe delivery status and logs

The receiver window prints the webhook payload body when delivery succeeds.

Review stored `DeliveryEvent` rows from the database:

```powershell
docker compose exec db sh -lc 'export PGPASSWORD="$POSTGRES_PASSWORD"; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT call_id, attempt_no, delivery_status, response_code, attempted_at, target_url, error_message FROM delivery_events ORDER BY call_id, attempt_no;"'
```

Review structured pipeline logs from the app:

```powershell
docker compose logs app-api | Select-String 'app.pipeline'
```

Three demo-ready Stage 5 scenarios are listed in `data/demo/stage5-demo-scenarios.md`.

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
