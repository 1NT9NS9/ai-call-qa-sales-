from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.adapters.delivery import (
    WebhookConfigurationError,
    WebhookDeliveryAdapter,
    WebhookDeliveryError,
    build_webhook_delivery_adapter,
)
from src.infrastructure.persistence.models import (
    CallAnalysis,
    CallProcessingStatus,
    CallSession,
    DeliveryEvent,
)
from src.observability import log_pipeline_event


class ExportNotFoundError(RuntimeError):
    pass


class ExportNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportResult:
    result_id: int
    status: str
    delivered_at: str
    target_url: str
    response_code: int | None = None


class ExportService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        delivery_adapter: WebhookDeliveryAdapter | None = None,
        webhook_target_url: str | None = None,
        app_env: str = "local",
    ) -> None:
        self._session_factory = session_factory
        self._delivery_adapter = delivery_adapter or build_webhook_delivery_adapter(
            target_url=webhook_target_url,
            app_env=app_env,
        )

    def deliver(self, call_id: int) -> ExportResult:
        export_started_at = perf_counter()
        delivery_payload = self._build_delivery_payload(call_id=call_id)
        attempted_at = self._parse_attempted_at(delivery_payload["deliveredAt"])
        log_pipeline_event(
            event="export.started",
            call_id=call_id,
            stage="export",
            status="started",
        )

        try:
            delivery_receipt = self._delivery_adapter.deliver(delivery_payload)
        except WebhookDeliveryError as exc:
            attempt_no = self._record_delivery_event(
                call_id=call_id,
                target_url=exc.target_url,
                attempted_at=attempted_at,
                delivery_status="failed",
                response_code=exc.response_status_code,
                error_message=str(exc),
            )
            log_pipeline_event(
                event="webhook.delivery_result",
                call_id=call_id,
                stage="export",
                status="failed",
                attempt_no=attempt_no,
                target_url=exc.target_url,
                response_code=exc.response_status_code,
                duration_ms=round((perf_counter() - export_started_at) * 1000, 2),
            )
            raise
        except WebhookConfigurationError:
            raise

        attempt_no = self._record_delivery_event(
            call_id=call_id,
            target_url=delivery_receipt.target_url,
            attempted_at=attempted_at,
            delivery_status="success",
            response_code=delivery_receipt.response_status_code,
            error_message=None,
        )
        self._mark_call_exported(call_id=call_id)
        log_pipeline_event(
            event="webhook.delivery_result",
            call_id=call_id,
            stage="export",
            status="success",
            processing_status=CallProcessingStatus.EXPORTED.value,
            attempt_no=attempt_no,
            target_url=delivery_receipt.target_url,
            response_code=delivery_receipt.response_status_code,
            duration_ms=round((perf_counter() - export_started_at) * 1000, 2),
        )

        return ExportResult(
            result_id=call_id,
            status=delivery_payload["status"],
            delivered_at=delivery_payload["deliveredAt"],
            target_url=delivery_receipt.target_url,
            response_code=delivery_receipt.response_status_code,
        )

    def _build_delivery_payload(self, *, call_id: int) -> dict[str, Any]:
        with self._session_factory() as session:
            call_session = session.get(CallSession, call_id)
            if call_session is None:
                raise ExportNotFoundError(f"CallSession not found for call_id={call_id}.")

            if call_session.processing_status == CallProcessingStatus.EXPORTED:
                raise ExportNotReadyError(
                    f"CallSession {call_id} has already been exported."
                )

            if call_session.processing_status != CallProcessingStatus.ANALYZED:
                raise ExportNotReadyError(
                    f"CallSession {call_id} is not ready for export."
                )

            analysis = session.get(CallAnalysis, call_id)
            if analysis is None or analysis.result_json is None:
                raise ExportNotReadyError(
                    f"CallSession {call_id} does not have a completed result to export."
                )

            return {
                "resultId": call_id,
                "status": "completed",
                "deliveredAt": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "result": analysis.result_json,
            }

    def _mark_call_exported(self, *, call_id: int) -> None:
        with self._session_factory() as session:
            call_session = session.get(CallSession, call_id)
            if call_session is None:
                raise ExportNotFoundError(f"CallSession not found for call_id={call_id}.")

            call_session.processing_status = CallProcessingStatus.EXPORTED
            session.commit()

    def _record_delivery_event(
        self,
        *,
        call_id: int,
        target_url: str,
        attempted_at: datetime,
        delivery_status: str,
        response_code: int | None,
        error_message: str | None,
    ) -> int:
        with self._session_factory() as session:
            next_attempt_no = self._next_attempt_no(session=session, call_id=call_id)
            session.add(
                DeliveryEvent(
                    call_id=call_id,
                    target_url=target_url,
                    delivery_status=delivery_status,
                    response_code=response_code,
                    attempt_no=next_attempt_no,
                    attempted_at=attempted_at,
                    error_message=error_message,
                )
            )
            session.commit()
        return next_attempt_no

    @staticmethod
    def _next_attempt_no(*, session: Session, call_id: int) -> int:
        current_attempt = session.scalar(
            select(func.max(DeliveryEvent.attempt_no)).where(
                DeliveryEvent.call_id == call_id
            )
        )
        return int(current_attempt or 0) + 1

    @staticmethod
    def _parse_attempted_at(delivered_at: str) -> datetime:
        return datetime.fromisoformat(delivered_at.replace("Z", "+00:00"))


def build_export_service(
    *,
    session_factory: sessionmaker[Session],
    delivery_adapter: WebhookDeliveryAdapter | None = None,
    webhook_target_url: str | None = None,
    app_env: str = "local",
) -> ExportService:
    return ExportService(
        session_factory=session_factory,
        delivery_adapter=delivery_adapter,
        webhook_target_url=webhook_target_url,
        app_env=app_env,
    )
