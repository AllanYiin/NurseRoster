from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

ENV_SECTIONS: Sequence[Tuple[str, Sequence[Tuple[str, str]]]] = (
    (
        "# 後端服務埠設定",
        (
            ("BACKEND_HOST", "127.0.0.1"),
            ("BACKEND_PORT", "8000"),
            ("APP_HOST", "127.0.0.1"),
            ("APP_PORT", "8000"),
        ),
    ),
    (
        "# 若未使用前端，可保留預設值供日後擴充",
        (
            ("FRONTEND_HOST", "127.0.0.1"),
            ("FRONTEND_PORT", "5173"),
            ("FRONTEND_URL", "http://127.0.0.1:5173"),
            ("API_BASE_URL", "http://127.0.0.1:8000"),
        ),
    ),
    (
        "# 資料儲存路徑（建議掛載至持久化磁碟）",
        (
            ("DATA_DIR", "./data"),
            ("LOG_DIR", "./logs"),
            ("EXPORT_DIR", "./exports"),
            ("DB_PATH", "./data/app.db"),
        ),
    ),
    (
        "# LLM 設定（未填寫則啟用 mock）",
        (
            ("OPENAI_API_KEY", ""),
            ("OPENAI_RESPONSES_MODEL", "gpt-4.1"),
        ),
    ),
    (
        "# 啟動時是否跳過預設種子資料",
        (("SKIP_SEED", "0"),),
    ),
)


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "generate_env_example.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
    )


def _flatten_lines(sections: Iterable[Tuple[str, Iterable[Tuple[str, str]]]]) -> List[str]:
    lines: List[str] = []
    for header, items in sections:
        lines.append(header)
        for key, value in items:
            lines.append(f"{key}={value}")
        lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def build_env_example() -> str:
    lines = _flatten_lines(ENV_SECTIONS)
    return "\n".join(lines) + "\n"


def write_env_example(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    content = build_env_example()
    target.write_text(content, encoding="utf-8")
    logging.info("已更新 .env.example 到 %s", target.resolve())


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a fresh .env.example file for NurseRoster.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".env.example"),
        help="Path to write the generated .env.example file (default: %(default)s).",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("logs"),
        help="Directory to store generator logs (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_dir)

    try:
        write_env_example(args.output)
    except Exception:
        logging.exception("產生 .env.example 時發生未預期錯誤")
        return 1

    logging.info("已完成 .env.example 產生流程")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(levelname)s] %(message)s")
        logging.exception("Unhandled exception while generating .env.example")
        sys.exit(1)
