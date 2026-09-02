import logging
import sys
import json
import re
from datetime import datetime, timezone


_SECRET_RE = re.compile(
    r"(?i)(\b(?:api[_-]?master[_-]?key|api[_-]?key(?:[_-]?pepper)?|webhook[_-]?secret|authorization|bearer)\b\s*[:=]\s*)([^\s,;}]+)"
)
_SESSION_RE = re.compile(
    r"(?i)(\b(?:session(?:[_-]?id)?|qr(?:[_-]?code)?)\b\s*[:=]\s*)([^\s,;}]+)"
)
_PHONE_RE = re.compile(r"(?<!\d)\+?\d{10,15}(?!\d)")


def redact_log_text(value: str) -> str:
    """Remove secrets and direct identifiers from application log text."""
    value = _SECRET_RE.sub(r"\1[REDACTED]", value)
    value = _SESSION_RE.sub(r"\1[REDACTED]", value)
    return _PHONE_RE.sub("[PHONE_REDACTED]", value)


class StructuredJsonFormatter(logging.Formatter):
    """Formatador de log estruturado em JSON sem expor segredos ou PII."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_text(record.getMessage()),
        }
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = getattr(record, "correlation_id")
        if hasattr(record, "tenant_id"):
            log_obj["tenant_id"] = getattr(record, "tenant_id")
        if record.exc_info:
            log_obj["exception"] = redact_log_text(self.formatException(record.exc_info))
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(log_level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredJsonFormatter())
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    # Remove handlers anteriores para não duplicar
    root_logger.handlers = [handler]
