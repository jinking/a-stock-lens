#!/usr/bin/env python3
"""从 JSON 文件或 stdin 读取一个 pytest 失败，并调用 Jev 分类。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from astock_lens.ai.jev import classify_test_failure


def _load_env_fallback() -> None:
    """若环境中未显式设置 TYPESAFE_API_KEY，尝试从当前工作区 .env 读取。"""
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    env_path = Path(".env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                if (
                    k.strip() == "TYPESAFE_API_KEY"
                    and "TYPESAFE_API_KEY" not in os.environ
                ):
                    os.environ["TYPESAFE_API_KEY"] = v.strip().strip("\"'")
    except OSError:
        return


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 TypeSafe Jev 分类单个 pytest 失败"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="输入 JSON 文件；省略或使用 '-' 时从 stdin 读取",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="TypeSafe 请求超时秒数，默认 15",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="输出单行 JSON",
    )
    return parser.parse_args(argv)


def _read_state(source: str) -> dict[str, Any]:
    if source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("输入必须是 JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    _load_env_fallback()
    args = _parse_args(argv)

    try:
        state = _read_state(args.input)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "available": False,
                    "category": "uncertain",
                    "confidence": 0.0,
                    "probabilities": {},
                    "model": None,
                    "usage": {"input_tokens": None, "output_tokens": None},
                    "request_id": None,
                    "error": f"输入错误: {exc}",
                },
                ensure_ascii=False,
            )
        )
        return 2

    result = classify_test_failure(state, timeout_seconds=args.timeout)
    indent = None if args.compact else 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=indent))

    # Jev 不可用是可恢复状态，不能让测试/Agent 主流程失败。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
