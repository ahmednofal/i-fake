"""Structured logging with Rich console output."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logger(
    name: str = "i_fake",
    level: str = "INFO",
    log_dir: Path | None = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        console = RichHandler(rich_tracebacks=True, show_path=False, markup=True)
        console.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.addHandler(console)

        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "i_fake.log")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
            )
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "i_fake") -> logging.Logger:
    return logging.getLogger(name)
