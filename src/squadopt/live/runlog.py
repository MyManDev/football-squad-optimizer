"""Structured run logging for the live path.

A scheduled tick that prints to a console nobody is watching leaves no trace of what it
did or why it stopped. ``configure_run_logging`` gives one run of a live component a
``run_id`` and two sinks: a human-readable line on the console (what an operator sees
when running by hand) and one JSON object per event appended to a daily ``.jsonl`` file
under the log root (what a scheduler, a dashboard, or a post-mortem reads). Library code
logs through the standard ``logging`` module as usual; only the entry point configures
handlers, so importing the package never writes a file.
"""

import json
import logging
import secrets
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

LIVE_LOGGER_NAME: Final = "squadopt"
_CONSOLE_FORMAT: Final = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class JsonLineFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, run id, message, extra fields."""

    def __init__(self, run_id: str, component: str) -> None:
        super().__init__()
        self._run_id = run_id
        self._component = component

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "component": self._component,
            "run_id": self._run_id,
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, Mapping):
            payload["fields"] = {str(k): _jsonable(v) for k, v in fields.items()}
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def _jsonable(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    return str(value)


class RunLog:
    """A logger bound to one run: ``event(name, **fields)`` writes a structured record."""

    def __init__(self, logger: logging.Logger, run_id: str, log_path: Path | None) -> None:
        self.logger = logger
        self.run_id = run_id
        self.log_path = log_path

    def event(self, name: str, **fields: object) -> None:
        self.logger.info(name, extra={"fields": fields})

    def failure(self, name: str, **fields: object) -> None:
        """Record a handled failure with the active exception's traceback."""

        self.logger.error(name, exc_info=True, extra={"fields": fields})


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def configure_run_logging(
    component: str,
    *,
    log_root: Path | None = None,
    run_id: str | None = None,
    console: bool = True,
    level: int = logging.INFO,
) -> RunLog:
    """Attach the console and JSON-lines sinks for one run of ``component``.

    ``log_root/<component>/<YYYY-MM-DD>.jsonl`` receives every record (appended, so
    several runs a day share a file and stay distinguishable by ``run_id``); ``None``
    keeps logging in memory only (tests, dry runs). Calling this twice in a process
    replaces the sinks it installed before rather than stacking them.
    """

    if not isinstance(component, str) or not component.strip():
        raise ValueError("component must be a non-empty string.")
    identifier = run_id or new_run_id()
    root_logger = logging.getLogger(LIVE_LOGGER_NAME)
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        if getattr(handler, "_squadopt_run_handler", False):
            root_logger.removeHandler(handler)
            handler.close()
    log_path: Path | None = None
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))
        stream._squadopt_run_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(stream)
    if log_root is not None:
        directory = Path(log_root) / component
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonLineFormatter(identifier, component))
        file_handler._squadopt_run_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)
    return RunLog(logging.getLogger(f"{LIVE_LOGGER_NAME}.{component}"), identifier, log_path)
