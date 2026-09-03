from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 只能填写 true 或 false")


@dataclass(frozen=True)
class Settings:
    business_api_base_url: str = "http://127.0.0.1:8088"
    business_api_timeout_seconds: float = 3.0
    business_api_max_retries: int = 2
    award_detail_transport: str = "rest"
    award_detail_mcp_url: str = "http://127.0.0.1:8088/mcp"
    award_detail_mcp_initialization_timeout_seconds: float = 5.0
    award_detail_mcp_call_timeout_seconds: float = 5.0
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    rag_embedding_api_key: str | None = None
    rag_embedding_base_url: str | None = None
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_batch_size: int = 10
    rag_chunk_size: int = 400
    rag_chunk_overlap: int = 60
    rag_index_dir: str = "knowledge/index"
    rag_collection_name: str = "incentive-business-rules"
    rag_enabled: bool = False
    rag_relevance_threshold: float = 0.30
    rag_top_k: int = 3
    agent_host: str = "127.0.0.1"
    agent_port: int = 8090
    agent_cache_size: int = 128
    agent_session_cache_size: int = 1024
    agent_session_ttl_seconds: int = 3600
    agent_context_max_tokens: int = 6000
    agent_context_max_turns: int = 12
    agent_auth_secret: str | None = None
    agent_auth_issuer: str = "incentive-agent"
    agent_auth_audience: str = "incentive-agent-web"
    agent_access_token_ttl_seconds: int = 3600
    agent_observability_enabled: bool = False
    agent_observability_queue_capacity: int = 1000
    agent_observability_retention_days: int = 30
    agent_observability_mysql_host: str = "127.0.0.1"
    agent_observability_mysql_port: int = 3306
    agent_observability_mysql_database: str = "budou"
    agent_observability_mysql_user: str = "root"
    agent_observability_mysql_password: str = "root"
    agent_observability_mysql_connect_timeout: int = 3
    operator_access_token: str | None = None
    operator_id: str = "local-operator"
    operator_permissions: frozenset[str] = frozenset(
        {
            "campaign:read",
            "campaign:draft",
            "campaign:review",
            "campaign:publish",
            "campaign:metric",
            "agent:observe",
        }
    )
    exchange_confirmation_ttl_seconds: int = 120
    exchange_confirmation_capacity: int = 10_000
    exchange_confirmation_store: str = "memory"
    exchange_confirmation_redis_url: str = "redis://127.0.0.1:6379/0"
    exchange_confirmation_redis_prefix: str = "agent:exchange:confirmation"
    exchange_confirmation_retention_seconds: int = 3600
    growth_memory_store: str = "memory"
    growth_memory_redis_url: str = "redis://127.0.0.1:6379/0"
    growth_memory_redis_prefix: str = "agent:growth:memory"
    growth_memory_mysql_host: str = "127.0.0.1"
    growth_memory_mysql_port: int = 3306
    growth_memory_mysql_database: str = "budou"
    growth_memory_mysql_user: str = "root"
    growth_memory_mysql_password: str = "root"
    growth_memory_mysql_table: str = "agent_long_term_memory"
    growth_memory_mysql_connect_timeout: int = 3

    def __post_init__(self) -> None:
        if self.award_detail_transport not in {"rest", "mcp"}:
            raise ValueError("AWARD_DETAIL_TRANSPORT 仅支持 rest 或 mcp")
        if self.award_detail_mcp_initialization_timeout_seconds <= 0:
            raise ValueError(
                "AWARD_DETAIL_MCP_INITIALIZATION_TIMEOUT_SECONDS 必须大于 0"
            )
        if self.award_detail_mcp_call_timeout_seconds <= 0:
            raise ValueError("AWARD_DETAIL_MCP_CALL_TIMEOUT_SECONDS 必须大于 0")
        if self.agent_observability_queue_capacity <= 0:
            raise ValueError("AGENT_OBSERVABILITY_QUEUE_CAPACITY 必须大于 0")
        if not 1 <= self.agent_observability_retention_days <= 30:
            raise ValueError("AGENT_OBSERVABILITY_RETENTION_DAYS 必须在 1 到 30 之间")
        if self.agent_observability_mysql_connect_timeout <= 0:
            raise ValueError("AGENT_OBSERVABILITY_MYSQL_CONNECT_TIMEOUT 必须大于 0")
        if self.award_detail_transport == "mcp":
            self._validate_award_detail_mcp_url()

    def _validate_award_detail_mcp_url(self) -> None:
        parsed = urlparse(self.award_detail_mcp_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("AWARD_DETAIL_MCP_URL 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("AWARD_DETAIL_MCP_URL 不允许包含凭据、查询参数或片段")
        hostname = parsed.hostname.lower()
        is_loopback = hostname == "localhost"
        if not is_loopback:
            try:
                is_loopback = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError("AWARD_DETAIL_MCP_URL 仅允许访问本机回环地址")
        if parsed.path.rstrip("/") != "/mcp":
            raise ValueError("AWARD_DETAIL_MCP_URL 路径必须是 /mcp")

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
            award_detail_transport=os.getenv(
                "AWARD_DETAIL_TRANSPORT", "rest"
            ).strip().lower(),
            award_detail_mcp_url=os.getenv(
                "AWARD_DETAIL_MCP_URL", "http://127.0.0.1:8088/mcp"
            ).strip(),
            award_detail_mcp_initialization_timeout_seconds=float(
                os.getenv(
                    "AWARD_DETAIL_MCP_INITIALIZATION_TIMEOUT_SECONDS",
                    "5",
                )
            ),
            award_detail_mcp_call_timeout_seconds=float(
                os.getenv("AWARD_DETAIL_MCP_CALL_TIMEOUT_SECONDS", "5")
            ),
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_base_url=os.getenv("LLM_BASE_URL") or None,
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            rag_embedding_api_key=(
                os.getenv("RAG_EMBEDDING_API_KEY")
                or os.getenv("LLM_API_KEY")
                or None
            ),
            rag_embedding_base_url=(
                os.getenv("RAG_EMBEDDING_BASE_URL")
                or os.getenv("LLM_BASE_URL")
                or None
            ),
            rag_embedding_model=os.getenv(
                "RAG_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            rag_embedding_batch_size=int(
                os.getenv("RAG_EMBEDDING_BATCH_SIZE", "10")
            ),
            rag_chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "400")),
            rag_chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "60")),
            rag_index_dir=os.getenv("RAG_INDEX_DIR", "knowledge/index").strip(),
            rag_collection_name=os.getenv(
                "RAG_COLLECTION_NAME", "incentive-business-rules"
            ).strip(),
            rag_enabled=env_bool("RAG_ENABLED", False),
            rag_relevance_threshold=float(
                os.getenv("RAG_RELEVANCE_THRESHOLD", "0.30")
            ),
            rag_top_k=int(os.getenv("RAG_TOP_K", "3")),
            agent_host=os.getenv("AGENT_HOST", "127.0.0.1"),
            agent_port=int(os.getenv("AGENT_PORT", "8090")),
            agent_cache_size=int(os.getenv("AGENT_CACHE_SIZE", "128")),
            agent_session_cache_size=int(
                os.getenv("AGENT_SESSION_CACHE_SIZE", "1024")
            ),
            agent_session_ttl_seconds=int(
                os.getenv("AGENT_SESSION_TTL_SECONDS", "3600")
            ),
            agent_context_max_tokens=int(
                os.getenv("AGENT_CONTEXT_MAX_TOKENS", "6000")
            ),
            agent_context_max_turns=int(
                os.getenv("AGENT_CONTEXT_MAX_TURNS", "12")
            ),
            agent_auth_secret=os.getenv("AGENT_AUTH_SECRET") or None,
            agent_auth_issuer=os.getenv("AGENT_AUTH_ISSUER", "incentive-agent"),
            agent_auth_audience=os.getenv(
                "AGENT_AUTH_AUDIENCE", "incentive-agent-web"
            ),
            agent_access_token_ttl_seconds=int(
                os.getenv("AGENT_ACCESS_TOKEN_TTL_SECONDS", "3600")
            ),
            agent_observability_enabled=env_bool(
                "AGENT_OBSERVABILITY_ENABLED", False
            ),
            agent_observability_queue_capacity=int(
                os.getenv("AGENT_OBSERVABILITY_QUEUE_CAPACITY", "1000")
            ),
            agent_observability_retention_days=int(
                os.getenv("AGENT_OBSERVABILITY_RETENTION_DAYS", "30")
            ),
            agent_observability_mysql_host=os.getenv(
                "AGENT_OBSERVABILITY_MYSQL_HOST",
                os.getenv("GROWTH_MEMORY_MYSQL_HOST", "127.0.0.1"),
            ).strip(),
            agent_observability_mysql_port=int(
                os.getenv(
                    "AGENT_OBSERVABILITY_MYSQL_PORT",
                    os.getenv("GROWTH_MEMORY_MYSQL_PORT", "3306"),
                )
            ),
            agent_observability_mysql_database=os.getenv(
                "AGENT_OBSERVABILITY_MYSQL_DATABASE",
                os.getenv("GROWTH_MEMORY_MYSQL_DATABASE", "budou"),
            ).strip(),
            agent_observability_mysql_user=os.getenv(
                "AGENT_OBSERVABILITY_MYSQL_USER",
                os.getenv(
                    "GROWTH_MEMORY_MYSQL_USER",
                    os.getenv("SPRING_DATASOURCE_USERNAME", "root"),
                ),
            ).strip(),
            agent_observability_mysql_password=os.getenv(
                "AGENT_OBSERVABILITY_MYSQL_PASSWORD",
                os.getenv(
                    "GROWTH_MEMORY_MYSQL_PASSWORD",
                    os.getenv("SPRING_DATASOURCE_PASSWORD", "root"),
                ),
            ),
            agent_observability_mysql_connect_timeout=int(
                os.getenv("AGENT_OBSERVABILITY_MYSQL_CONNECT_TIMEOUT", "3")
            ),
            operator_access_token=os.getenv("OPERATOR_ACCESS_TOKEN") or None,
            operator_id=os.getenv("OPERATOR_ID", "local-operator").strip(),
            operator_permissions=frozenset(
                item.strip()
                for item in os.getenv(
                    "OPERATOR_PERMISSIONS",
                    "campaign:read,campaign:draft,campaign:review,campaign:publish,campaign:metric,agent:observe",
                ).split(",")
                if item.strip()
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
            growth_memory_store=os.getenv(
                "GROWTH_MEMORY_STORE", "mysql"
            ).strip().lower(),
            growth_memory_redis_url=(
                os.getenv("GROWTH_MEMORY_REDIS_URL")
                or os.getenv(
                    "EXCHANGE_CONFIRMATION_REDIS_URL",
                    "redis://127.0.0.1:6379/0",
                )
            ).strip(),
            growth_memory_redis_prefix=os.getenv(
                "GROWTH_MEMORY_REDIS_PREFIX",
                "agent:growth:memory",
            ).strip(),
            growth_memory_mysql_host=os.getenv(
                "GROWTH_MEMORY_MYSQL_HOST", "127.0.0.1"
            ).strip(),
            growth_memory_mysql_port=int(
                os.getenv("GROWTH_MEMORY_MYSQL_PORT", "3306")
            ),
            growth_memory_mysql_database=os.getenv(
                "GROWTH_MEMORY_MYSQL_DATABASE", "budou"
            ).strip(),
            growth_memory_mysql_user=os.getenv(
                "GROWTH_MEMORY_MYSQL_USER",
                os.getenv("SPRING_DATASOURCE_USERNAME", "root"),
            ).strip(),
            growth_memory_mysql_password=os.getenv(
                "GROWTH_MEMORY_MYSQL_PASSWORD",
                os.getenv("SPRING_DATASOURCE_PASSWORD", "root"),
            ),
            growth_memory_mysql_table=os.getenv(
                "GROWTH_MEMORY_MYSQL_TABLE", "agent_long_term_memory"
            ).strip(),
            growth_memory_mysql_connect_timeout=int(
                os.getenv("GROWTH_MEMORY_MYSQL_CONNECT_TIMEOUT", "3")
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

    def require_rag_embedding_api_key(self) -> str:
        if not self.rag_embedding_api_key:
            raise ValueError(
                "缺少 RAG_EMBEDDING_API_KEY。可以单独配置，或复用 LLM_API_KEY。"
            )
        return self.rag_embedding_api_key
