"""Logging configuration for Times Tables Quest.

Provides circular in-memory log buffer for the web UI,
and persistent rotating file logging in data/app_debug.log.
"""

from __future__ import annotations

import collections
import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List

LOG_BUFFER: collections.deque = collections.deque(maxlen=200)
LOG_FILE_PATH = Path("data/app_debug.log")


class MemoryLogHandler(logging.Handler):
    """Stores recent log records in memory for retrieval via web API."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            LOG_BUFFER.append({
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
            })
        except Exception:
            self.handleError(record)


class NintendoApiOnlyFilter(logging.Filter):
    """Strictly filter logs so that ONLY Nintendo server API requests and responses are kept."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "nintendo.api":
            return True
        msg = record.getMessage()
        return (
            ">> Nintendo API Request" in msg
            or "<< Nintendo API Response" in msg
            or "<< Nintendo API Error" in msg
            or ">> Nintendo API POST" in msg
        )


def setup_logging(log_file: Path = LOG_FILE_PATH, debug: bool = True) -> None:
    """Initialize root logging with memory and rotating file handlers."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Clean existing handlers
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    api_filter = NintendoApiOnlyFilter()

    # 1. Console Handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)
    root.addHandler(console)

    # 2. File Handler - ONLY records Nintendo server API requests/responses
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(api_filter)
    root.addHandler(file_handler)

    # 3. Memory Handler for Web UI - ONLY records Nintendo server API requests/responses
    mem_handler = MemoryLogHandler()
    mem_handler.setFormatter(logging.Formatter("%(message)s"))
    mem_handler.setLevel(logging.INFO)
    mem_handler.addFilter(api_filter)
    root.addHandler(mem_handler)

    # Quiet all verbose third-party and internal loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("pynintendoparental").setLevel(logging.WARNING)
    logging.getLogger("pynintendoauth").setLevel(logging.WARNING)
    logging.getLogger("app.main").setLevel(logging.WARNING)
    logging.getLogger("app.learning").setLevel(logging.WARNING)
    logging.getLogger("app.db").setLevel(logging.WARNING)

    # Keep nintendo API logger active
    logging.getLogger("nintendo.api").setLevel(logging.INFO)


def get_recent_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Return the most recent log entries."""
    logs = list(LOG_BUFFER)
    return logs[-limit:]


def clear_logs() -> None:
    """Clear memory log buffer and truncate debug log file."""
    LOG_BUFFER.clear()
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                f.truncate(0)
        except Exception:
            pass

