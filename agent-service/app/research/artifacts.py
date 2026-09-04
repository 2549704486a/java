from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,95}$")
_SAFE_FILENAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}\.json$")


class ResearchRunStore:
    """Writes immutable JSON artifacts below one dedicated run root."""

    def __init__(self, runs_root: str | Path) -> None:
        self._runs_root = Path(runs_root).resolve()

    def create_run_directory(
        self,
        *,
        experiment_id: str,
        arm: str,
        run_id: str,
    ) -> Path:
        for name, value in {
            "experiment_id": experiment_id,
            "arm": arm,
            "run_id": run_id,
        }.items():
            if not _SAFE_COMPONENT.fullmatch(value):
                raise ValueError(f"{name} 不是安全的运行目录名")
        run_directory = self._ensure_below_root(
            self._runs_root / experiment_id / arm / run_id
        )
        run_directory.mkdir(parents=True, exist_ok=False)
        return run_directory

    def create_evaluation_directory(
        self,
        *,
        experiment_id: str,
        evaluation_id: str,
    ) -> Path:
        for name, value in {
            "experiment_id": experiment_id,
            "evaluation_id": evaluation_id,
        }.items():
            if not _SAFE_COMPONENT.fullmatch(value):
                raise ValueError(f"{name} 不是安全的评估目录名")
        evaluation_directory = self._ensure_below_root(
            self._runs_root / experiment_id / "evaluation" / evaluation_id
        )
        evaluation_directory.mkdir(parents=True, exist_ok=False)
        return evaluation_directory

    def write_json_once(
        self,
        run_directory: str | Path,
        filename: str,
        value: BaseModel | dict[str, Any] | list[Any],
    ) -> Path:
        if not _SAFE_FILENAME.fullmatch(filename):
            raise ValueError("运行产物文件名必须是安全的小写 JSON 文件名")
        checked_directory = self._ensure_below_root(Path(run_directory).resolve())
        if not checked_directory.is_dir():
            raise ValueError("运行目录不存在")
        output_path = self._ensure_below_root(checked_directory / filename)
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        with output_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        return output_path

    def _ensure_below_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self._runs_root and self._runs_root not in resolved.parents:
            raise ValueError("运行产物不能写出隔离目录")
        return resolved
