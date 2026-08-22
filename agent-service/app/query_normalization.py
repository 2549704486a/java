"""将常见错别字和口语表达保守地转换为业务标准 Query。"""

from __future__ import annotations

import re
from dataclasses import dataclass


# 只收录能够明确映射到当前积分兑换领域的表达，避免通用纠错误改用户意图。
DOMAIN_QUERY_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("处里", "处理"),
    ("成攻", "成功"),
    ("任物", "任务"),
    ("积份", "积分"),
    ("奖厉", "奖励"),
    ("自已", "自己"),
    ("到帐", "到账"),
    ("活干完了", "任务完成了"),
    ("咋分还没到账", "积分为什么还没到账"),
    ("到底能干啥", "具体能做什么"),
    ("替我下单不", "替我兑换奖品吗"),
)


@dataclass(frozen=True)
class QueryNormalizationResult:
    """保留原始和标准化 Query，便于双路召回而不是强制覆盖用户输入。"""

    original_query: str
    normalized_query: str
    applied_replacements: tuple[tuple[str, str], ...]

    @property
    def variants(self) -> tuple[str, ...]:
        if self.normalized_query == self.original_query:
            return (self.original_query,)
        return (self.original_query, self.normalized_query)


def normalize_business_query(query: str) -> QueryNormalizationResult:
    """执行确定性、可回溯的领域标准化，不调用模型猜测用户意图。"""
    original = re.sub(r"\s+", " ", query).strip()
    if not original:
        raise ValueError("query 不能为空")

    normalized = original
    applied: list[tuple[str, str]] = []
    for source, target in DOMAIN_QUERY_REPLACEMENTS:
        if source not in normalized:
            continue
        normalized = normalized.replace(source, target)
        applied.append((source, target))

    return QueryNormalizationResult(
        original_query=original,
        normalized_query=normalized,
        applied_replacements=tuple(applied),
    )
