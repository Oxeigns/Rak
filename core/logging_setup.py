from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'function': record.funcName,
        }
        for key in ('user_id', 'chat_id', 'action', 'error_type'):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info:
            payload['stack_trace'] = ''.join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str) -> None:
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
