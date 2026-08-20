from __future__ import annotations

import logging

import uvicorn
from dotenv import load_dotenv

from app.config import Settings
from app.logging_config import configure_logging
from app.web import app


logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    log_path = configure_logging()
    settings = Settings.from_env()
    logger.info(
        "agent_http_boot host=%s port=%s model=%s log_file=%s",
        settings.agent_host,
        settings.agent_port,
        settings.llm_model,
        log_path,
    )
    uvicorn.run(
        app,
        host=settings.agent_host,
        port=settings.agent_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
