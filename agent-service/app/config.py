from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    business_api_base_url: str = "http://127.0.0.1:8088"
    business_api_timeout_seconds: float = 3.0
    business_api_max_retries: int = 2
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            business_api_base_url=os.getenv(
                "BUSINESS_API_BASE_URL", "http://127.0.0.1:8088"
            ).rstrip("/"),
            business_api_timeout_seconds=float(
                os.getenv("BUSINESS_API_TIMEOUT_SECONDS", "3")
            ),
            business_api_max_retries=int(
                os.getenv("BUSINESS_API_MAX_RETRIES", "2")
            ),
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        )

    def require_llm_api_key(self) -> str:
        if not self.llm_api_key:
            raise ValueError(
                "缺少 LLM_API_KEY。若只想验证业务规划，可改用 --plan-award-id。"
            )
        return self.llm_api_key

