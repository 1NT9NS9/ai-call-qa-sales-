# Tasks for Stage 1

## Assumptions
- Stage 1 scope is limited to [docs/stages/README.md](/C:/IT/project/hr-resume/ai-call-qa-sales/docs/stages/README.md), [docs/stages/stage-1-database.md](/C:/IT/project/hr-resume/ai-call-qa-sales/docs/stages/stage-1-database.md), and the `docs/CONTRACTS.md` entity list referenced directly by the Stage 1 exit criteria.
- `all core entities required by CONTRACTS.md` is interpreted as the persisted objects listed under `Persisted Objects`; Stage 1 does not require implementing STT, RAG, or analysis behavior.
- `basic CallSession create flow` means one application path can create and persist a `CallSession` end to end; it does not imply full lifecycle progression or CRUD for every entity.
- `stable enough to attach uploaded audio and transcript data` is satisfied by a persisted `CallSession` model that includes `audio_storage_key` plus a persisted `TranscriptSegment` relation, without implementing upload or transcription behavior.

## Task List

### T1. Model `CallSession` and lifecycle status
- Estimate: 1-2h
- Goal: Represent the core call record in the persistence layer and store lifecycle state in the database.
- Do:
  - Add or confirm the `CallSession` persistence model with `id`, `external_call_id`, `processing_status`, `audio_storage_key`, `source_type`, `metadata`, and timestamps.
  - Ensure `processing_status` is part of the persisted model and uses the lifecycle value set defined in `CONTRACTS.md`.
  - Keep the work limited to persistence structure; do not add upload, STT, RAG, or analysis behavior.
- Result:
  - A persisted `CallSession` model exists and includes stored lifecycle status plus the fields needed for later audio attachment.
- Verification:
  - The persistence definition includes every `CallSession` field named in `CONTRACTS.md`.
  - `processing_status` is stored as a database-backed field on `CallSession`.
- Depends on:
  - None.

### T2. Model `TranscriptSegment` persistence
- Estimate: 1-2h
- Goal: Represent transcript segment storage without implementing transcription.
- Do:
  - Add or confirm the `TranscriptSegment` persistence model with `id`, `call_id`, `speaker`, `text`, `start_ms`, `end_ms`, and `sequence_no`.
  - Link `TranscriptSegment.call_id` to `CallSession`.
  - Keep the work limited to schema and relationships only.
- Result:
  - Transcript segments can be stored against a `CallSession` in the persistence layer.
- Verification:
  - The persistence definition includes every `TranscriptSegment` field named in `CONTRACTS.md`.
  - The schema includes a relationship from `TranscriptSegment.call_id` to `CallSession`.
- Depends on:
  - T1.

### T3. Model knowledge-base persistence entities
- Estimate: 1-2h
- Goal: Represent the Stage 1 knowledge-storage entities required by the contract.
- Do:
  - Add or confirm a persisted `KnowledgeDocument` record for the original knowledge-base document.
  - Add or confirm the `KnowledgeChunk` persistence model with `id`, `document_id`, `chunk_text`, `embedding`, and `chunk_index`.
  - Link `KnowledgeChunk.document_id` to `KnowledgeDocument`.
  - Limit the work to persistence representation only; do not add retrieval or embedding generation behavior.
- Result:
  - The knowledge-base document and chunk entities are represented in the persistence layer.
- Verification:
  - `KnowledgeDocument` exists in the persistence layer.
  - The persistence definition includes every explicitly named `KnowledgeChunk` field from `CONTRACTS.md`.
  - The schema includes a relationship from `KnowledgeChunk.document_id` to `KnowledgeDocument`.
- Depends on:
  - None.

### T4. Model `CallAnalysis` review storage separately from lifecycle status
- Estimate: 1-2h
- Goal: Persist analysis result storage fields while keeping review state separate from `CallSession.processing_status`.
- Do:
  - Add or confirm the `CallAnalysis` persistence model with `call_id`, `result_json`, `confidence`, `review_required`, `review_reasons`, `model_name`, `prompt_version`, and timestamps.
  - Link `CallAnalysis.call_id` to `CallSession`.
  - Store `review_required` and `review_reasons` on `CallAnalysis`, not as lifecycle status on `CallSession`.
  - Do not implement any analysis execution, retry logic, or scoring behavior.
- Result:
  - Analysis persistence fields exist, and review state is stored separately from call lifecycle state.
- Verification:
  - The persistence definition includes every `CallAnalysis` field named in `CONTRACTS.md`.
  - Schema review shows review fields live on `CallAnalysis` while `CallSession.processing_status` remains a lifecycle field.
- Depends on:
  - T1.

### T5. Model `DeliveryEvent` persistence
- Estimate: 1-2h
- Goal: Represent outbound delivery attempt storage without implementing outbound delivery behavior.
- Do:
  - Add or confirm the `DeliveryEvent` persistence model with `call_id`, `target_url`, `delivery_status`, `response_code`, `attempt_no`, and `error_message`.
  - Link `DeliveryEvent.call_id` to `CallSession`.
  - Keep the work limited to persistence fields and relationships.
- Result:
  - Delivery attempts can be recorded in the persistence layer.
- Verification:
  - The persistence definition includes every `DeliveryEvent` field named in `CONTRACTS.md`.
  - The schema includes a relationship from `DeliveryEvent.call_id` to `CallSession`.
- Depends on:
  - T1.

### T6. Generate migration files for the current Stage 1 schema
- Estimate: 1-2h
- Goal: Produce migration files that can create the full current Stage 1 schema from an empty database.
- Do:
  - Generate or update migration files for `CallSession`, `TranscriptSegment`, `KnowledgeDocument`, `KnowledgeChunk`, `CallAnalysis`, and `DeliveryEvent`.
  - Include the relationships needed by the modeled entities.
  - Keep the migration scope limited to the current Stage 1 schema.
- Result:
  - Migration files exist for the full Stage 1 persistence model.
- Verification:
  - Migration files are present in the repository.
  - Applying the migrations on a clean database creates the current schema for all Stage 1 entities.
- Depends on:
  - T1, T2, T3, T4, T5.

### T7. Implement the basic `POST /calls` create flow
- Estimate: 1-2h
- Goal: Make the Stage 1 application entrypoint create and persist a `CallSession` end to end.
- Do:
  - Add or confirm `POST /calls` as the `CallSession` creation entrypoint defined by [docs/ARCHITECTURE.md](/C:/IT/project/hr-resume/ai-call-qa-sales/docs/ARCHITECTURE.md).
  - Wire that endpoint into the existing FastAPI application created in [apps/app-api/src/main.py](/C:/IT/project/hr-resume/ai-call-qa-sales/apps/app-api/src/main.py).
  - Persist the required `CallSession` fields through the `POST /calls` flow.
  - Ensure the flow stores `processing_status` in the database as part of creation.
  - Keep the flow limited to create behavior only.
- Result:
  - `POST /calls` can create a persisted `CallSession`.
- Verification:
  - Sending a request through `POST /calls` creates a `CallSession` row in the database.
  - The created row contains a stored `processing_status` value.
- Depends on:
  - T1, T6.

### T8. Run the bounded Stage 1 persistence verification
- Estimate: 1-2h
- Goal: Validate the Stage 1 schema and create flow against the stated exit criteria and readiness boundaries.
- Do:
  - Apply the Stage 1 migrations on a clean database.
  - Confirm each persisted object named in `CONTRACTS.md` is represented in the resulting schema.
  - Execute `POST /calls` and inspect the stored `CallSession` record.
  - Confirm analysis review fields are stored separately from lifecycle status.
  - Record any failed checks as specific follow-up corrections instead of remediating them inside T8.
- Result:
  - Stage 1 has a concrete validation result for schema coverage, migration sufficiency, and `CallSession` persistence.
- Verification:
  - The clean database can be created from migration files alone.
  - All Stage 1 persisted entities are present in the schema.
  - A `CallSession` can be created through the application flow.
  - `CallSession.processing_status` is stored in the database.
  - `CallAnalysis.review_required` and `CallAnalysis.review_reasons` remain separate from lifecycle status storage.
- Depends on:
  - T6, T7.

## Exit Criteria Coverage
- `all core entities required by ../CONTRACTS.md are represented in the persistence layer` -> T1, T2, T3, T4, T5, T6, T8
- `migration files exist and are sufficient to create the current schema` -> T6, T8
- `a CallSession can be created through the application flow` -> T1, T7, T8
- `CallSession.processing_status is stored in the database` -> T1, T6, T7, T8
- `analysis review fields are stored separately from lifecycle status` -> T4, T6, T8

## Risks / Ambiguities
- `KnowledgeDocument` is named in `CONTRACTS.md` but no explicit field list is provided there; Stage 1 work should keep this entity minimal and avoid inventing extra document metadata.
- The source documents require storing lifecycle status values but do not specify whether enforcement must occur at the database level, application level, or both.
- The source documents do not specify whether migrations must be one baseline file or multiple files, only that they must be sufficient to create the current schema.
- If T8 finds failed checks, they must be decomposed into separate correction tasks rather than expanding T8 beyond verification.

## Proposed Execution Order
1. T1. Model `CallSession` and lifecycle status
2. T2. Model `TranscriptSegment` persistence
3. T3. Model knowledge-base persistence entities
4. T4. Model `CallAnalysis` review storage separately from lifecycle status
5. T5. Model `DeliveryEvent` persistence
6. T6. Generate migration files for the current Stage 1 schema
7. T7. Implement the basic `POST /calls` create flow
8. T8. Run the bounded Stage 1 persistence verification

## Final Checks
- Every task is bounded to 1-2 hours including verification.
- No task extends beyond Stage 1 database scope or introduces STT, RAG, or analysis behavior.
- Every task is traceable to Stage 1 in-scope work, required deliverables, exit criteria, readiness needs, or constraints.
- Every Stage 1 exit criterion is covered in `Exit Criteria Coverage`; none remain unresolved from the source material.
- This document is Markdown only.
