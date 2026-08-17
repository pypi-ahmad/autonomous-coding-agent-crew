from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from agent_crew.settings import RUNS_DIR

LOG_PATH = RUNS_DIR / "agent-crew.log"
MAX_BYTES = 2_000_000
BACKUP_COUNT = 3


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("agent_crew")
    if logger.handlers:
        return logger
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return configure_logging()
