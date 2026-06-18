"""Central logging configuration for OndePi.

Historically OndePi never called ``logging.basicConfig`` / ``dictConfig``, so the
``general.log_level`` config field was dead and every ``logger.info``/``debug``
call in the codebase was silently dropped (the root logger sat at WARNING with no
handler).  In the field this meant the journal contained only uvicorn's own lines
— making remote diagnosis nearly impossible.

This module wires a single stderr handler (journald-friendly) and applies the
configured level to the ``ondepi`` package logger, while keeping noisy
third-party libraries (asyncio, sounddevice, etc.) at WARNING.
"""

from __future__ import annotations

import logging

# Marker so we never attach two OndePi handlers (e.g. if configure() runs twice
# in tests or after a config reload).
_HANDLER_FLAG = "_ondepi_handler"

_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

DEFAULT_LEVEL = logging.INFO


def resolve_level(level_name: str | None) -> int:
    """Map a config string to a logging level, defaulting to INFO."""
    if not level_name:
        return DEFAULT_LEVEL
    return _LEVELS.get(str(level_name).strip().lower(), DEFAULT_LEVEL)


def configure_logging(level_name: str | None, *, package: str = "ondepi") -> int:
    """Configure logging for the application.

    - Attaches exactly one stderr handler to the root logger (idempotent).
    - Sets the ``ondepi`` package logger to the configured level so its
      INFO/DEBUG records are emitted; leaves the root at WARNING so third-party
      libraries stay quiet.

    Returns the resolved numeric level (useful for tests/callers).
    """
    level = resolve_level(level_name)
    root = logging.getLogger()

    if not any(getattr(h, _HANDLER_FLAG, False) for h in root.handlers):
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_FLAG, True)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)

    # Keep the root (and thus third-party libs) at WARNING; records originating
    # in the ondepi package still reach the root handler because propagation
    # does not re-check ancestor levels.
    if root.level == logging.NOTSET or root.level > logging.WARNING:
        root.setLevel(logging.WARNING)
    logging.getLogger(package).setLevel(level)
    return level
