from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class WebhookConfigurationError(RuntimeError):
    pass


class WebhookDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        target_url: str,
        response_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.target_url = target_url
        self.response_status_code = response_status_code


@dataclass(frozen=True)
class WebhookDeliveryReceipt:
    target_url: str
    response_status_code: int


class WebhookDeliveryAdapter:
    def __init__(
        self,
        *,
        target_url: str | None,
        app_env: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._target_url = target_url
        self._app_env = app_env
        self._timeout_seconds = timeout_seconds

    def deliver(self, payload: dict[str, Any]) -> WebhookDeliveryReceipt:
        target_url = self._validated_target_url()

        try:
            with httpx.Client(timeout=self._timeout_seconds, trust_env=False) as client:
                response = client.post(target_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WebhookDeliveryError(
                str(exc),
                target_url=target_url,
                response_status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise WebhookDeliveryError(
                str(exc),
                target_url=target_url,
            ) from exc

        return WebhookDeliveryReceipt(
            target_url=target_url,
            response_status_code=response.status_code,
        )

    def _validated_target_url(self) -> str:
        if not self._target_url:
            raise WebhookConfigurationError("WEBHOOK_TARGET_URL is not configured.")

        parsed_url = urlparse(self._target_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise WebhookConfigurationError("WEBHOOK_TARGET_URL must be a valid HTTP URL.")

        if parsed_url.scheme != "https" and self._app_env not in {"local", "test"}:
            raise WebhookConfigurationError(
                "WEBHOOK_TARGET_URL must use HTTPS outside local development."
            )

        return self._target_url


def build_webhook_delivery_adapter(
    *,
    target_url: str | None,
    app_env: str,
) -> WebhookDeliveryAdapter:
    return WebhookDeliveryAdapter(
        target_url=target_url,
        app_env=app_env,
    )
