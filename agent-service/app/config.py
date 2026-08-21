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
    agent_host: str = "127.0.0.1"
    agent_port: int = 8090
    agent_cache_size: int = 128
    agent_session_cache_size: int = 1024
    agent_auth_secret: str | None = None
    agent_auth_issuer: str = "incentive-agent"
    agent_auth_audience: str = "incentive-agent-web"
    agent_access_token_ttl_seconds: int = 3600
    exchange_confirmation_ttl_seconds: int = 120
    exchange_confirmation_capacity: int = 10_000
    exchange_confirmation_store: str = "memory"
    exchange_confirmation_redis_url: str = "redis://127.0.0.1:6379/0"
    exchange_confirmation_redis_prefix: str = "agent:exchange:confirmation"
    exchange_confirmation_retention_seconds: int = 3600

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
            agent_host=os.getenv("AGENT_HOST", "127.0.0.1"),
            agent_port=int(os.getenv("AGENT_PORT", "8090")),
            agent_cache_size=int(os.getenv("AGENT_CACHE_SIZE", "128")),
            agent_session_cache_size=int(
                os.getenv("AGENT_SESSION_CACHE_SIZE", "1024")
            ),
            agent_auth_secret=os.getenv("AGENT_AUTH_SECRET") or None,
            agent_auth_issuer=os.getenv("AGENT_AUTH_ISSUER", "incentive-agent"),
            agent_auth_audience=os.getenv(
                "AGENT_AUTH_AUDIENCE", "incentive-agent-web"
            ),
            agent_access_token_ttl_seconds=int(
                os.getenv("AGENT_ACCESS_TOKEN_TTL_SECONDS", "3600")
            ),
            exchange_confirmation_ttl_seconds=int(
                os.getenv("EXCHANGE_CONFIRMATION_TTL_SECONDS", "120")
            ),
            exchange_confirmation_capacity=int(
                os.getenv("EXCHANGE_CONFIRMATION_CAPACITY", "10000")
            ),
            exchange_confirmation_store=os.getenv(
                "EXCHANGE_CONFIRMATION_STORE", "redis"
            ).strip().lower(),
            exchange_confirmation_redis_url=os.getenv(
                "EXCHANGE_CONFIRMATION_REDIS_URL", "redis://127.0.0.1:6379/0"
            ).strip(),
            exchange_confirmation_redis_prefix=os.getenv(
                "EXCHANGE_CONFIRMATION_REDIS_PREFIX",
                "agent:exchange:confirmation",
            ).strip(),
            exchange_confirmation_retention_seconds=int(
                os.getenv("EXCHANGE_CONFIRMATION_RETENTION_SECONDS", "3600")
            ),
        )

    def require_llm_api_key(self) -> str:
        if not self.llm_api_key:
            raise ValueError(
                "缺少 LLM_API_KEY。若只想验证业务规划，可改用 --plan-award-id。"
            )
        return self.llm_api_key

    def require_auth_secret(self) -> str:
        if not self.agent_auth_secret:
            raise ValueError(
                "缺少 AGENT_AUTH_SECRET。请生成至少 32 字符的随机密钥并写入 .env。"
            )
        return self.agent_auth_secret
