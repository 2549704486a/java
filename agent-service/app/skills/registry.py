"""发现、校验并按需加载文件型 Skill。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)

REQUIRED_METADATA = ("name", "description", "trigger", "version")
REQUIRED_SECTIONS = (
    "何时使用",
    "输入",
    "执行步骤",
    "错误与重试",
    "安全边界",
    "输出",
)
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


class SkillDefinitionError(ValueError):
    """Skill 声明缺失、冲突或不满足项目约定。"""


@dataclass(frozen=True)
class SkillManifest:
    """启动阶段可以提供给模型的精简 Skill 元数据。"""

    name: str
    description: str
    trigger: str
    version: str
    tags: tuple[str, ...]
    source_path: Path

    @property
    def tool_description(self) -> str:
        return (
            f"仅在已经加载 {self.name} Skill 后使用。{self.description} "
            f"触发条件：{self.trigger}"
        )

    def trace_metadata(self) -> dict[str, str]:
        return {
            "skill_name": self.name,
            "skill_version": self.version,
        }


@dataclass(frozen=True)
class SkillDefinition:
    """命中任务后才返回给模型的完整 Skill 定义。"""

    manifest: SkillManifest
    instructions: str

    def as_tool_result(self) -> dict:
        return {
            "success": True,
            "code": "SKILL_LOADED",
            "data": {
                "name": self.manifest.name,
                "version": self.manifest.version,
                "instructions": self.instructions,
            },
            "message": "Skill 执行说明已加载，请按照 instructions 完成当前任务",
            "retryable": False,
        }


class SkillRegistry:
    """启动时发现元数据，任务命中后按名称加载完整正文。"""

    def __init__(self, skills_dir: Path | str = DEFAULT_SKILLS_DIR) -> None:
        self.skills_dir = Path(skills_dir).resolve()
        self._definitions = self._discover()

    def manifests(self) -> tuple[SkillManifest, ...]:
        return tuple(
            definition.manifest
            for _, definition in sorted(self._definitions.items())
        )

    def require_manifest(self, name: str) -> SkillManifest:
        return self._require(name).manifest

    def load(
        self,
        name: str,
        *,
        allowed_names: Iterable[str] | None = None,
    ) -> SkillDefinition:
        if allowed_names is not None and name not in frozenset(allowed_names):
            raise SkillDefinitionError(f"当前 Agent 不允许加载 Skill：{name}")
        definition = self._require(name)
        logger.info(
            "skill_loaded name=%s version=%s",
            definition.manifest.name,
            definition.manifest.version,
        )
        return definition

    def catalog(self, names: Iterable[str]) -> str:
        """生成启动时披露给模型的目录，不包含 Skill 正文。"""

        manifests = [self.require_manifest(name) for name in names]
        lines = ["以下仅为 Skill 目录，正文尚未加载："]
        for manifest in manifests:
            lines.extend(
                (
                    f"- {manifest.name}: {manifest.description}",
                    f"  触发条件：{manifest.trigger}",
                )
            )
        return "\n".join(lines)

    def trace_metadata(self) -> list[dict[str, str]]:
        return [manifest.trace_metadata() for manifest in self.manifests()]

    def _require(self, name: str) -> SkillDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._definitions)) or "无"
            raise SkillDefinitionError(
                f"未注册 Skill：{name}；当前可用：{available}"
            ) from exc

    def _discover(self) -> dict[str, SkillDefinition]:
        if not self.skills_dir.is_dir():
            raise SkillDefinitionError(f"Skill 目录不存在：{self.skills_dir}")

        definitions: dict[str, SkillDefinition] = {}
        for skill_path in sorted(self.skills_dir.glob("*/SKILL.md")):
            definition = self._load_definition(skill_path)
            name = definition.manifest.name
            if skill_path.parent.name != name:
                raise SkillDefinitionError(
                    f"Skill 名称必须与目录名一致：{skill_path.parent.name} != {name}"
                )
            if name in definitions:
                raise SkillDefinitionError(f"Skill 名称重复：{name}")
            definitions[name] = definition

        if not definitions:
            raise SkillDefinitionError(f"Skill 目录中没有 SKILL.md：{self.skills_dir}")
        return definitions

    @staticmethod
    def _load_definition(skill_path: Path) -> SkillDefinition:
        content = skill_path.read_text(encoding="utf-8-sig")
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise SkillDefinitionError(f"SKILL.md 缺少 YAML Front Matter：{skill_path}")

        try:
            metadata = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            raise SkillDefinitionError(f"SKILL.md 元数据无法解析：{skill_path}") from exc
        if not isinstance(metadata, dict):
            raise SkillDefinitionError(f"SKILL.md 元数据必须是对象：{skill_path}")

        missing = [
            key
            for key in REQUIRED_METADATA
            if not isinstance(metadata.get(key), (str, int, float))
            or not str(metadata[key]).strip()
        ]
        if missing:
            raise SkillDefinitionError(
                f"SKILL.md 缺少有效元数据 {missing}：{skill_path}"
            )

        instructions = parts[2].strip()
        missing_sections = [
            section
            for section in REQUIRED_SECTIONS
            if f"## {section}" not in instructions
        ]
        if missing_sections:
            raise SkillDefinitionError(
                f"SKILL.md 缺少章节 {missing_sections}：{skill_path}"
            )

        raw_tags = metadata.get("tags") or []
        if not isinstance(raw_tags, list) or not all(
            isinstance(tag, str) and tag.strip() for tag in raw_tags
        ):
            raise SkillDefinitionError(f"SKILL.md tags 必须是字符串数组：{skill_path}")

        manifest = SkillManifest(
            name=str(metadata["name"]).strip(),
            description=str(metadata["description"]).strip(),
            trigger=str(metadata["trigger"]).strip(),
            version=str(metadata["version"]).strip(),
            tags=tuple(tag.strip() for tag in raw_tags),
            source_path=skill_path.resolve(),
        )
        return SkillDefinition(manifest=manifest, instructions=instructions)
