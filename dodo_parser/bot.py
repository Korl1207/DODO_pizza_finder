from __future__ import annotations

import time

from .dodo import DodoHTTPError
from .notify import TelegramClient
from .report import build_report, resolve_pizza_name


CHECK_COMMANDS = {"/check", "/check_pizza"}
HELP_TEXT = (
    "Проверка запускается только командами.\n"
    "По умолчанию бот берет `pizza_name` из config.json.\n"
    "Команды:\n"
    "/check_pizza - проверить пиццу из config.json\n"
    "/check_pizza Пепперони - временно проверить другую пиццу\n"
    "/check - короткий алиас для /check_pizza"
)
UNKNOWN_COMMAND_TEXT = (
    "Доступны команды /check_pizza и /check.\n"
    "Без аргумента используется pizza_name из config.json.\n"
    "С аргументом ищется указанная пицца, например: /check_pizza Пепперони"
)
CHECK_FAILED_PREFIX = "Проверка не выполнена: "


def run_bot(config: dict) -> None:
    token = config.get("telegram_bot_token")
    if not token:
        raise RuntimeError("telegram_bot_token is required for --bot mode")

    allowed_chat_id = str(config.get("telegram_chat_id") or "").strip()
    client = TelegramClient(token=token)
    offset: int | None = None

    while True:
        updates = client.get_updates(offset=offset, timeout=30)
        for update in updates:
            offset = int(update["update_id"]) + 1
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            if allowed_chat_id and chat_id != allowed_chat_id:
                continue

            text = (message.get("text") or "").strip()
            if text in {"/start", "/help"}:
                client.send_message(chat_id=chat_id, text=HELP_TEXT)
                continue

            command_arg = _extract_check_argument(text)
            if command_arg is not None:
                pizza_name = resolve_pizza_name(config, command_arg or None)
                client.send_message(chat_id=chat_id, text=f"Проверяю Dodo для: {pizza_name}")
                try:
                    report = build_report(config, pizza_name=pizza_name)
                except (DodoHTTPError, RuntimeError) as exc:
                    report = f"{CHECK_FAILED_PREFIX}{exc}"
                for chunk in _split_message(report):
                    client.send_message(chat_id=chat_id, text=chunk)
                continue

            command, _ = _parse_command(text)
            if command:
                client.send_message(chat_id=chat_id, text=UNKNOWN_COMMAND_TEXT)

        time.sleep(1)


def _parse_command(text: str) -> tuple[str | None, str]:
    if not text.startswith("/"):
        return None, ""

    parts = text.split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


def _extract_check_argument(text: str) -> str | None:
    command, argument = _parse_command(text)
    if command not in CHECK_COMMANDS:
        return None
    return argument


def _split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks
