from __future__ import annotations

import logging
import os
from pathlib import Path


def configure_logging() -> Path:
    service_root = Path(__file__).resolve().parents[1]
    default_log_path = service_root / "logs" / "agent-service.log"
    log_path = Path(os.getenv("AGENT_LOG_FILE") or default_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level_name = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[file_handler], force=True)
    return log_path
