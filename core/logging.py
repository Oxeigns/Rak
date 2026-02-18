from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'function_name': record.funcName,
            'handler_name': getattr(record, 'handler_name', None),
            'user_id': getattr(record, 'user_id', None),
            'chat_id': getattr(record, 'chat_id', None),
            'action': getattr(record, 'action', None),
            'error_type': getattr(record, 'error_type', None),
        }

        if record.exc_info:
            payload['stack_trace'] = ''.join(traceback.format_exception(*record.exc_info)).strip()

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
