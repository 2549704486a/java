from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.runner import CASES_PATH, evaluate_case, summarize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用最新规则离线重评已有结果")
    parser.add_argument("--input", nargs="+", required=True, help="一个或多个结果 JSON")
    parser.add_argument("--output", required=True, help="重评分结果 JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = {
        case["id"]: case
        for case in json.loads(CASES_PATH.read_text(encoding="utf-8"))
    }
    results: list[dict[str, Any]] = []
    source_files = []
    for input_name in args.input:
        input_path = Path(input_name)
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        source_files.append(str(input_path))
        for result in payload["results"]:
            case = cases[result["id"]]
            result["evaluation"] = evaluate_case(
                case,
                result.get("response", ""),
                result.get("tool_calls", []),
                result.get("backend_calls", []),
            )
            results.append(result)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "metadata": {
            "rescored_at": datetime.now().isoformat(timespec="seconds"),
            "source_files": source_files,
            "case_ids": [result["id"] for result in results],
        },
        "summary": summarize(results),
        "results": results,
    }
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"重评分结果已保存：{output_path}")


if __name__ == "__main__":
    main()

