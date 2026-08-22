from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.growth_memory_store import MemoryType
from app.models import MemoryItem


MEMORY_TYPE_ALIASES: dict[MemoryType, tuple[str, ...]] = {
    "preference": ("偏好", "喜欢", "不喜欢", "讨厌"),
    "goal": ("目标", "计划", "打算", "想要"),
    "profile": ("个人信息", "身份", "职业", "习惯"),
    "episode": ("经历", "发生过", "事件"),
}


def select_memories(
    memories: Iterable[MemoryItem],
    *,
    query: str | None,
    memory_types: list[MemoryType] | None,
    limit: int,
    include_all: bool,
) -> list[MemoryItem]:
    """从少量用户记忆中做可解释的确定性召回，不依赖向量服务。"""
    active = [item for item in memories if item.status == "ACTIVE"]
    active.sort(key=lambda item: item.updated_at, reverse=True)
    if include_all:
        return active

    requested_types = set(memory_types or [])
    candidates = [
        item for item in active if not requested_types or item.memory_type in requested_types
    ]
    cleaned_query = _normalize_text(query or "")
    if not cleaned_query:
        return candidates[:limit]

    ranked: list[tuple[int, float, MemoryItem]] = []
    for item in candidates:
        score = _relevance_score(cleaned_query, item)
        # 明确限定了类型时，即使问题很泛，也可以按新鲜度取该类型记忆；
        # 没有限定类型时则必须有文本相关证据，避免把无关记忆注入模型。
        if score > 0 or requested_types:
            ranked.append((score, item.updated_at.timestamp(), item))
    ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [item for _, _, item in ranked[:limit]]


def _relevance_score(query: str, item: MemoryItem) -> int:
    subject = _normalize_text(str(item.normalized_data.get("subject", "")))
    candidate = _normalize_text(
        " ".join(
            [
                item.raw_text,
                *(_scalar_values(item.normalized_data)),
                *MEMORY_TYPE_ALIASES[item.memory_type],
            ]
        )
    )
    query_compact = query.replace(" ", "")
    candidate_compact = candidate.replace(" ", "")
    score = 0
    if query_compact and query_compact in candidate_compact:
        score += 100
    if candidate_compact and candidate_compact in query_compact:
        score += 90
    if subject and subject.replace(" ", "") in query_compact:
        score += 80

    query_units = _lexical_units(query)
    candidate_units = _lexical_units(candidate)
    score += len(query_units & candidate_units) * 8
    return score


def _scalar_values(value: dict) -> list[str]:
    return [str(item) for item in value.values() if isinstance(item, (str, int, float, bool))]


def _lexical_units(value: str) -> set[str]:
    units: set[str] = set()
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) == 1:
                continue
            units.update(token[index : index + 2] for index in range(len(token) - 1))
        else:
            units.add(token)
    return units


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized).strip()
