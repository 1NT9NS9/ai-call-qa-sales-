from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
)


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
        delivery_payload = self._build_delivery_payload(call_id=call_id)
        delivery_receipt = self._delivery_adapter.deliver(delivery_payload)
        self._mark_call_exported(call_id=call_id)

        return ExportResult(
            result_id=call_id,
            status=delivery_payload["status"],
            delivered_at=delivery_payload["deliveredAt"],
            target_url=delivery_receipt.target_url,
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
