# Contracts Specification

## Purpose

This document defines the core contracts used by the MVP.
It covers lifecycle rules, persisted objects, analysis output, and approved internal tools.

System flow is defined in [ARCHITECTURE.md](ARCHITECTURE.md).
Integration boundaries are defined in [INTEGRATIONS.md](INTEGRATIONS.md).
Security handling for contract data is defined in [SECURITY.md](SECURITY.md).

## Call Lifecycle

`CallSession.processing_status` may only use these values:

- `created`
- `uploaded`
- `transcribed`
- `analyzed`
- `exported`
- `failed`

`review_required` is not a lifecycle status. It is a quality flag on the analysis result.

## Persisted Objects

- `CallSession`: `id`, `external_call_id`, `processing_status`, `audio_storage_key`, `source_type`, `metadata`, `created_at`, `updated_at`
- `TranscriptSegment`: `id`, `call_id`, `speaker`, `text`, `start_ms`, `end_ms`, `sequence_no`
- `KnowledgeDocument`: original knowledge-base document record
- `KnowledgeChunk`: `id`, `document_id`, `chunk_text`, `embedding`, `chunk_index`
- `CallAnalysis`: `call_id`, `result_json`, `confidence`, `review_required`, `review_reasons`, `model_name`, `prompt_version`, `created_at`, `updated_at`
- `DeliveryEvent`: `call_id`, `target_url`, `delivery_status`, `response_code`, `attempt_no`, `error_message`

## Analysis Result Contract

The final analysis result shall include:

- `summary`
- `score`
- `score_breakdown`
- `objections`
- `risks`
- `next_best_action`
- `coach_feedback`
- `used_knowledge`
- `confidence`
- `needs_review`
- `review_reasons`

Contract details:

- `score_breakdown` is a list of `{ criterion, score, max_score, reason }`
- `objections` is a list of `{ text, handled, evidence_segment_ids }`
- `risks` is a list of `{ text, severity, evidence_segment_ids }`
- `used_knowledge` is a list of `{ document_id, chunk_id, reason }`
- `needs_review` lives in the analysis payload
- persisted `review_required` mirrors the quality decision in storage

## Guardrails

- if the analysis JSON is invalid, retry once
- if it is still invalid, persist `CallAnalysis` with `review_required = true`
- if `confidence` is below threshold, persist `review_required = true`
- if the transcript is empty or too short, either fail the call or mark the analysis for review based on the implemented rule

## Approved Tool API

The analysis layer may call only these tools:

- `retrieve_context`
- `get_call_metadata`

Integration-level service contracts are defined in [INTEGRATIONS.md](INTEGRATIONS.md).
