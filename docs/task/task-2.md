# Tasks for Stage 2

## Assumptions
- Stage 2 builds on a system where an existing `CallSession` can already be created and referenced, because the stage scope starts from uploading audio for an existing call.
- `configured audio storage location` means an application storage target that is already chosen through configuration; this stage does not define or require selecting a new storage backend.

## Task List

### T1. Add the audio upload endpoint for existing calls
- Estimate: 1-2h
- Goal: Accept an audio file for an existing `CallSession`.
- Covers:
  - In Scope: implement audio upload
  - Required Deliverables: upload endpoint
  - Exit Criteria: `audio can be uploaded for an existing CallSession`
- Do:
  - Implement the Stage 2 upload endpoint required by the source document.
  - Bind the upload request to an existing `CallSession`.
- Result:
  - The system has an upload endpoint that accepts audio for an existing `CallSession`.
- Verification:
  - A request for an existing `CallSession` reaches the upload endpoint successfully and is associated with that call.
- Depends on:
  - None.

### T2. Persist uploaded audio and save `audio_storage_key`
- Estimate: 1-2h
- Goal: Store the uploaded file in the configured audio storage location and persist its storage key on the call.
- Covers:
  - In Scope: store `audio_storage_key`
  - Exit Criteria: `the uploaded file is stored in the configured audio storage location`
  - Exit Criteria: `audio_storage_key` is persisted for the call
- Do:
  - Write the uploaded audio file to the configured audio storage location.
  - Persist the resulting `audio_storage_key` on the target `CallSession`.
- Result:
  - The uploaded file exists in the configured storage location, and the call record stores `audio_storage_key`.
- Verification:
  - The uploaded file is present in the configured storage location.
  - The target `CallSession` record contains the persisted `audio_storage_key`.
- Depends on:
  - T1.

### T3. Implement the `STTAdapter` with one provider
- Estimate: 1-2h
- Goal: Keep transcription behind an adapter interface while using exactly one STT provider.
- Covers:
  - In Scope: implement `STTAdapter`
  - Required Deliverables: working STT adapter
  - Constraints: `use one STT provider only`
  - Constraints: `keep transcription behind the adapter interface`
  - Readiness For Stage 3: `exactly one STT provider is used behind the adapter interface`
- Do:
  - Add the `STTAdapter` interface required by Stage 2.
  - Implement one concrete STT provider behind that adapter.
  - Ensure the Stage 2 transcription path depends on the adapter interface rather than provider-specific calls.
- Result:
  - A working `STTAdapter` exists, and exactly one STT provider is used behind it.
- Verification:
  - Code review of the Stage 2 transcription path shows calls go through `STTAdapter`.
  - Configuration and wiring show only one provider is active behind the adapter.
- Depends on:
  - None.

### T4. Trigger transcription through `STTAdapter`
- Estimate: 1-2h
- Goal: Run transcription for uploaded audio through the adapter path.
- Covers:
  - Exit Criteria: `transcription runs through STTAdapter`
  - Constraints: `keep transcription behind the adapter interface`
- Do:
  - Invoke `STTAdapter` for the uploaded audio associated with the call.
  - Capture the transcript output needed for Stage 2 segmentation and storage work.
- Result:
  - The happy-path transcription run executes through `STTAdapter` for uploaded audio.
- Verification:
  - The task output names the happy-path trigger used to start transcription for Stage 2.
  - A successful Stage 2 run produces transcript output by calling `STTAdapter` rather than bypassing it.
- Depends on:
  - T2, T3.

### T5. Split transcript output into ordered segments
- Estimate: 1-2h
- Goal: Convert the transcript output into ordered `TranscriptSegment` records.
- Covers:
  - In Scope: split transcript into segments
  - Exit Criteria: `transcript output is split into ordered TranscriptSegment records`
- Do:
  - Transform the transcription result into a sequence of `TranscriptSegment` items.
  - Preserve a clear first-to-last order for the resulting segments.
- Result:
  - The transcription result is represented as ordered `TranscriptSegment` data ready for persistence.
- Verification:
  - The task output names the ordering mechanism used for `TranscriptSegment` records.
  - A happy-path transcription result produces `TranscriptSegment` items in deterministic order.
- Depends on:
  - T4.

### T6. Store `TranscriptSegment` records for the call
- Estimate: 1-2h
- Goal: Persist the transcript produced by Stage 2 and make the stored order retrievable for later use.
- Covers:
  - In Scope: store transcript segments
  - Required Deliverables: stored transcript
  - Exit Criteria: `transcript segments are stored in the database`
  - Readiness For Stage 3: `transcript data is available for retrieval and later analysis`
- Do:
  - Store the ordered `TranscriptSegment` records in the database for the target call.
  - Keep the stored segment order aligned with the sequence produced in T5.
  - Identify the retrieval query or internal path that reads transcript segments back in order for the Stage 2 response.
- Result:
  - The transcript is stored in the database as ordered `TranscriptSegment` records and can be read back in that order.
- Verification:
  - Database inspection shows `TranscriptSegment` records linked to the call in the expected order.
  - Retrieving transcript segments for the call through the query or internal path used by the Stage 2 response returns them in the expected order.
- Depends on:
  - T5.

### T7. Mark the call `transcribed` and return transcript data
- Estimate: 1-2h
- Goal: Complete the Stage 2 happy path by updating call status and returning transcript data.
- Covers:
  - In Scope: move call status to `transcribed`
  - Required Deliverables: stored transcript
  - Exit Criteria: `the call transitions to transcribed`
  - Exit Criteria: `the system returns transcript data together with status transcribed`
  - Readiness For Stage 3: `transcript data is available for retrieval and later analysis`
- Do:
  - Transition the call status to `transcribed` after transcript segments are stored.
  - Identify and update the concrete Stage 2 response path used by the happy path so it returns transcript data together with status `transcribed`.
- Result:
  - The call reaches `transcribed`, and the named Stage 2 response path returns transcript data with that status.
- Verification:
  - The persisted call status is `transcribed` after a successful Stage 2 run.
  - The task output names the concrete endpoint or response path used by the Stage 2 happy path.
  - That named response path includes transcript data together with status `transcribed`.
- Depends on:
  - T6.

### T8. Verify the happy-path transcript pipeline
- Estimate: 1-2h
- Goal: Confirm the Stage 2 pipeline is stable for the happy path and ready for Stage 3 handoff.
- Covers:
  - Exit Criteria: `audio can be uploaded for an existing CallSession`
  - Exit Criteria: `the uploaded file is stored in the configured audio storage location`
  - Exit Criteria: `audio_storage_key` is persisted for the call
  - Exit Criteria: `transcription runs through STTAdapter`
  - Exit Criteria: `transcript output is split into ordered TranscriptSegment records`
  - Exit Criteria: `transcript segments are stored in the database`
  - Exit Criteria: `the call transitions to transcribed`
  - Exit Criteria: `the system returns transcript data together with status transcribed`
  - Readiness For Stage 3: `the transcript pipeline is stable for the happy path`
  - Readiness For Stage 3: `transcript data is available for retrieval and later analysis`
  - Readiness For Stage 3: `exactly one STT provider is used behind the adapter interface`
- Do:
  - Execute an end-to-end happy-path run for an existing `CallSession` from audio upload through transcript return.
  - Confirm the run stores the audio file, persists `audio_storage_key`, invokes `STTAdapter`, creates ordered `TranscriptSegment` records, stores them, and ends with status `transcribed`.
  - Confirm transcript data is available from the system path implemented in T7 and remains retrievable after persistence.
  - Confirm exactly one STT provider is used behind the adapter interface.
- Result:
  - Stage 2 has a bounded verification result for the full happy-path upload-to-transcribed flow.
- Verification:
  - The verification output lists the concrete happy-path trigger named in T4.
  - The verification output lists the ordering mechanism named in T5.
  - Audio can be uploaded for an existing `CallSession`.
  - The uploaded file is stored in the configured audio storage location.
  - `audio_storage_key` is persisted for the call.
  - Transcription runs through `STTAdapter`.
  - Transcript output is split into ordered `TranscriptSegment` records.
  - Transcript segments are stored in the database.
  - The call transitions to `transcribed`.
  - The named Stage 2 response path returns transcript data together with status `transcribed`.
  - The persisted transcript remains retrievable in order through that same response path after storage.
  - Exactly one STT provider is used behind the adapter interface.
- Depends on:
  - T1, T2, T3, T4, T5, T6, T7.

## Exit Criteria Coverage
- `audio can be uploaded for an existing CallSession` -> T1, T8
- `the uploaded file is stored in the configured audio storage location` -> T2, T8
- `audio_storage_key` is persisted for the call -> T2, T8
- `transcription runs through STTAdapter` -> T3, T4, T8
- `transcript output is split into ordered TranscriptSegment records` -> T5, T8
- `transcript segments are stored in the database` -> T6, T8
- `the call transitions to transcribed` -> T7, T8
- `the system returns transcript data together with status transcribed` -> T7, T8

## Risks / Ambiguities
- Ambiguity: the source document does not specify whether transcription runs synchronously during upload or in a separate processing step.
- Ambiguity: the source document does not identify which system response path must return transcript data together with status `transcribed`.
- Missing detail: the stage defines ordered `TranscriptSegment` records but does not specify the exact segment field set or ordering key.
- Missing detail: the stage does not define file-type limits, file-size limits, or failure-path behavior; the decomposition stays on the explicit happy path.
- Missing detail: `stable for the happy path` is a readiness requirement, but the source document does not define a required number of runs or a required automated/manual verification form.
- Oversized stage items: None after decomposition.

## Proposed Execution Order
1. T1. Add the audio upload endpoint for existing calls
2. T2. Persist uploaded audio and save `audio_storage_key`
3. T3. Implement the `STTAdapter` with one provider
4. T4. Trigger transcription through `STTAdapter`
5. T5. Split transcript output into ordered segments
6. T6. Store `TranscriptSegment` records for the call
7. T7. Mark the call `transcribed` and return transcript data
8. T8. Verify the happy-path transcript pipeline

## Final Checks
- Every task is bounded to 1-2 hours including verification.
- No task extends beyond Stage 2 transcription scope or adds later-stage RAG, analysis, export, or broader architecture work.
- Every task is traceable to Stage 2 in-scope work, required deliverables, exit criteria, readiness requirements, or constraints.
- Every Stage 2 exit criterion is covered in `Exit Criteria Coverage`; none are unresolved from the source material.
- This document is Markdown only.
