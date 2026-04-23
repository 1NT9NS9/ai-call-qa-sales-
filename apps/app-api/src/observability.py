from __future__ import annotations

import json
import logging
from typing import Any


PIPELINE_LOGGER_NAME = "app.pipeline"


def get_pipeline_logger() -> logging.Logger:
    return logging.getLogger(PIPELINE_LOGGER_NAME)


def log_pipeline_event(**fields: Any) -> None:
    get_pipeline_logger().info(
        json.dumps(
            fields,
            sort_keys=True,
            default=str,
        )
    )
