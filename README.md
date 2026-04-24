# AI Call QA & Sales Coach MVP

A simple API for processing calls:

1. upload audio
2. get a transcript
3. analyze the conversation
4. optionally send the result to a webhook

## What You Need

- Docker Desktop
- [`.env.example`](C:\IT\project\hr-resume\ai-call-qa-sales\.env.example) as a template for `.env`
- an API key for analysis through an OpenAI-compatible endpoint
- a Gemini API key if you want to use Gemini for transcription

## Quick Start

Create a local `.env` file from `.env.example` before starting the stack.

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Fill in `.env`.

The minimum required values are:

- `OPENAI_API_KEY`
- `MODEL`
- `DATABASE_URL`
- `STORAGE_AUDIO_DIR`

If analysis should go through a proxy, set:

```env
OPENAI_BASE_URL=http://host.docker.internal:8317/v1
```

If you want to use Gemini for transcription, set:

```env
GEMINI_API_KEY=your_gemini_key
GEMINI_STT_MODEL=gemini-2.5-flash
```

Start the project from the repository root:

```powershell
docker compose up --build
```

Check that the API is running:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/health | Select-Object -ExpandProperty Content
```

Health endpoint:

- `GET http://127.0.0.1:8000/health`

Expected response:

```json
{"status":"ok"}
```

## Main Flow

### 1. Create a call

```powershell
$call = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/calls -ContentType 'application/json' -Body '{}'
$callId = $call.id
```

### 2. Upload audio

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/calls/$callId/audio" -Form @{ file = Get-Item .\storage\audio\demo1.mp3 }
```

### 3. Import the knowledge base

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/knowledge/import
```

### 4. Build embeddings

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/knowledge/embed
```

### 5. Run analysis

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/calls/$callId/analyze"
```

### 6. Get the result

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/calls/$callId"
```

The final analysis is returned in the `result` field.

## Main Endpoints

- `POST /calls`
- `POST /calls/{call_id}/audio`
- `POST /knowledge/import`
- `POST /knowledge/embed`
- `POST /calls/{call_id}/analyze`
- `GET /calls/{call_id}`
- `POST /calls/{call_id}/export`

## Current Status

- analysis works end-to-end
- transcription works
- results are stored in the database and returned through the API

## Exporting the Result

If `WEBHOOK_TARGET_URL` is set in `.env`, you can send the result to an external webhook:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/calls/$callId/export"
```

Delivery status can be reviewed in the `delivery_events` table (`DeliveryEvent`), and pipeline activity is visible in the `app.pipeline` logs.

Ready-made demo scenarios are available in `data/demo/stage5-demo-scenarios.md`.

## Structure

- [apps/app-api](C:\IT\project\hr-resume\ai-call-qa-sales\apps\app-api) - backend API
- [docs](C:\IT\project\hr-resume\ai-call-qa-sales\docs) - project documentation
- [storage/audio](C:\IT\project\hr-resume\ai-call-qa-sales\storage\audio) - local audio files
- [data/kb_seed](C:\IT\project\hr-resume\ai-call-qa-sales\data\kb_seed) - knowledge base source documents
