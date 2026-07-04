from __future__ import annotations

import time
from typing import Any

from .dodo import DodoHTTPError
from .notify import TelegramClient
from .report import build_report


CHECK_BUTTON_TEXT = "Проверить сейчас"
CHECK_COMMANDS = {"/check", "/check_pizza"}


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
                client.send_message(
                    chat_id=chat_id,
                    text=(
                        "Нажми кнопку, и я проверю, в каких точках Dodo сейчас "
                        "есть нужная пицца."
                    ),
                    reply_markup=_keyboard(),
                )
                continue

            command, command_arg = _parse_command(text)
            if text == CHECK_BUTTON_TEXT or command in CHECK_COMMANDS:
                check_config = dict(config)
                if command_arg:
                    check_config["pizza_name"] = command_arg
                check_config["check_pizzerias"] = True

                client.send_message(chat_id=chat_id, text="Проверяю Dodo...", reply_markup=_keyboard())
                try:
                    report = build_report(check_config)
                except (DodoHTTPError, RuntimeError) as exc:
                    report = f"Проверка не выполнена: {exc}"
                for chunk in _split_message(report):
                    client.send_message(chat_id=chat_id, text=chunk, reply_markup=_keyboard())
                continue

            client.send_message(
                chat_id=chat_id,
                text="Я понимаю /check_pizza, /check или кнопку ниже.",
                reply_markup=_keyboard(),
            )

        time.sleep(1)


def _keyboard() -> dict[str, Any]:
    return {
        "keyboard": [[{"text": CHECK_BUTTON_TEXT}]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _parse_command(text: str) -> tuple[str | None, str]:
    if not text.startswith("/"):
        return None, ""

    parts = text.split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


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
