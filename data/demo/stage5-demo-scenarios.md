# Stage 5 demo scenarios

These scenarios assume the local stack is running and the Stage 5 usage steps in `README.md` have already been followed once to create an analyzed sample call and a working local webhook receiver.

## Scenario 1. API returns the final result for a completed call

Goal: show that a completed call exposes the persisted final result through the existing API.

Steps:

1. Create or reuse an analyzed sample call and capture its `call_id`.
2. Run:

   ```powershell
   Invoke-RestMethod -Uri "http://127.0.0.1:8000/calls/$callId"
   ```

3. Confirm the response includes:
   - `processing_status` set to `analyzed` or `exported`
   - a non-null `result`
   - the final result fields such as `summary`, `score`, and `next_best_action`

Expected demo outcome:
- the API response proves the final result is available without a second read endpoint

## Scenario 2. Successful webhook delivery for a completed result

Goal: show the happy-path outbound `webhook` delivery flow.

Steps:

1. Start the local receiver from the `README.md` Stage 5 usage section.
2. Trigger export:

   ```powershell
   Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/calls/$callId/export"
   ```

3. Confirm the API response includes:
   - `result_id`
   - `status`
   - `delivered_at`
   - `target_url`
4. In the receiver window, confirm one payload was printed with:
   - `resultId`
   - `status`
   - `deliveredAt`
   - `result`

Expected demo outcome:
- one successful outbound webhook POST is shown for one completed result

## Scenario 3. Review stored `DeliveryEvent` rows and pipeline logs

Goal: show that delivery attempts are persisted and the pipeline progression is visible in logs.

Steps:

1. Query the stored delivery rows:

   ```powershell
   docker compose exec db sh -lc 'export PGPASSWORD="$POSTGRES_PASSWORD"; psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT call_id, attempt_no, delivery_status, response_code, attempted_at, target_url, error_message FROM delivery_events ORDER BY call_id, attempt_no;"'
   ```

2. Confirm the exported call has a `DeliveryEvent` row with:
   - the same `call_id`
   - `attempt_no = 1`
   - `delivery_status = success`
   - the expected `target_url`
3. Review the application logs:

   ```powershell
   docker compose logs app-api | Select-String 'app.pipeline'
   ```

4. Confirm the log trail shows the ordered progression:
   - `pipeline.started`
   - `transcription.completed`
   - `analysis.started`
   - `analysis.completed`
   - `export.started`
   - `webhook.delivery_result`

Expected demo outcome:
- one sample run shows both persisted delivery review data and a visible ordered stage trail through export
