from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .bot import run_bot
from .dodo import DodoHTTPError
from .notify import notify_telegram
from .report import build_report, load_config


def run_once(config: dict) -> None:
    report = build_report(config)
    print(report)

    token = config.get("telegram_bot_token")
    chat_id = config.get("telegram_chat_id")
    if token and chat_id:
        notify_telegram(token=token, chat_id=chat_id, text=report)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Dodo Pizza product availability.")
    parser.add_argument("--config", default="config.json", help="Path to JSON config.")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Repeat interval in seconds. 0 means run once.",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Run Telegram bot with a check button.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args(argv or sys.argv[1:])
    config = load_config(Path(args.config))

    if args.bot:
        run_bot(config)
        return 0

    if args.interval <= 0:
        try:
            run_once(config)
            return 0
        except DodoHTTPError as exc:
            print(f"Ошибка проверки: {exc}", file=sys.stderr)
            return 1

    while True:
        try:
            run_once(config)
        except DodoHTTPError as exc:
            print(f"Ошибка проверки: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
