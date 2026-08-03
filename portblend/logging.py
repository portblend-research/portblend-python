"""
portblend.logging

Standardized educational logger for PortBlend SDK terminal outputs.
Emits formatted operational steps (`[PORTBLEND]`) and quantitative risk insights (`[INSIGHT]`).
"""

import logging
import sys


class PortBlendFormatter(logging.Formatter):
    """
    Custom formatter prefixing messages with colored/styled tags.
    """
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if record.levelno >= logging.ERROR:
            return f"[ERROR] {msg}"
        elif record.levelno >= logging.WARNING:
            return f"[WARNING] {msg}"
        elif getattr(record, "is_insight", False):
            return f"[INSIGHT] {msg}"
        else:
            return f"[PORTBLEND] {msg}"


_logger_initialized = False


def setup_logger(level: int = logging.INFO) -> logging.Logger:
    global _logger_initialized
    logger = logging.getLogger("portblend")
    logger.setLevel(level)

    if not _logger_initialized:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = PortBlendFormatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        _logger_initialized = True

    return logger


def get_logger() -> logging.Logger:
    return setup_logger()


def log_insight(msg: str) -> None:
    """Log an educational quantitative insight."""
    logger = get_logger()
    extra = {"is_insight": True}
    logger.info(msg, extra=extra)
