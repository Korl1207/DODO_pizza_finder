from __future__ import annotations

import re
import time

from .bot_state import BotState
from .dodo import DodoHTTPError
from .notify import TelegramClient
from .report import build_nearby_report, build_report, resolve_pizza_name


CHECK_COMMANDS = {"/check", "/check_pizza"}
NEARBY_COMMANDS = {"/nearby", "/where"}
HELP_TEXT = (
    "Проверка запускается командами, а для поиска рядом можно прислать геопозицию.\n"
    "По умолчанию бот берет `pizza_name` из config.json.\n"
    "Команды:\n"
    "/check_pizza - проверить пиццу из config.json\n"
    "/check_pizza Пепперони - временно проверить другую пиццу\n"
    "/check - короткий алиас для /check_pizza\n"
    "/nearby - попросить геопозицию и найти ближайшие точки для последней пиццы\n"
    "/nearby Пепперони - сначала сменить пиццу, затем попросить геопозицию\n"
    "/where - короткий алиас для /nearby\n"
    "@botname где заказать - бот попросит геопозицию и найдёт ближайшие точки\n"
    "@botname Пепперони - бот запомнит пиццу и попросит геопозицию"
)
UNKNOWN_COMMAND_TEXT = (
    "Доступны команды /check_pizza, /check, /nearby и /where.\n"
    "Без аргумента используется pizza_name из config.json.\n"
    "С аргументом ищется указанная пицца, например: /check_pizza Пепперони.\n"
    "Для поиска рядом используйте /nearby или /where, затем отправьте геопозицию."
)
CHECK_FAILED_PREFIX = "Проверка не выполнена: "
LOCATION_REQUEST_TEXT = "Пришлите геопозицию Telegram следующим сообщением, и я найду ближайшие 10 пиццерий."
LOCATION_REQUEST_NEEDS_PIZZA_TEXT = (
    "Сначала скажите, какую пиццу искать: /check_pizza Пепперони, /nearby Пепперони или @botname Пепперони."
)
LOCATION_EXPIRED_TEXT = "Не нашёл активный запрос на геопозицию. Сначала напишите /nearby или @botname где заказать."


def run_bot(config: dict) -> None:
    token = config.get("telegram_bot_token")
    if not token:
        raise RuntimeError("telegram_bot_token is required for --bot mode")

    allowed_chat_id = str(config.get("telegram_chat_id") or "").strip()
    client = TelegramClient(token=token)
    state = BotState(config.get("bot_state_path", ".bot_state.json"))
    bot_usernames = _resolve_bot_usernames(client, config)
    primary_bot_username = bot_usernames[0] if bot_usernames else None
    pending_location_ttl_seconds = int(config.get("pending_location_ttl_seconds", 900) or 900)
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

            from_user = message.get("from") or {}
            user_id = str(from_user.get("id") or "")
            if user_id and message.get("location"):
                pizza_name = state.pop_pending_location_request(
                    chat_id,
                    user_id,
                    max_age_seconds=pending_location_ttl_seconds,
                )
                if pizza_name is None:
                    continue
                location = message.get("location") or {}
                latitude = float(location.get("latitude"))
                longitude = float(location.get("longitude"))
                client.send_message(chat_id=chat_id, text=f"Считаю ближайшие пиццерии для: {pizza_name}")
                report = build_nearby_report(
                    config,
                    latitude=latitude,
                    longitude=longitude,
                    pizza_name=pizza_name,
                )
                for chunk in _split_message(report):
                    client.send_message(chat_id=chat_id, text=chunk)
                continue

            text = (message.get("text") or "").strip()
            if text in {"/start", "/help"}:
                client.send_message(chat_id=chat_id, text=_render_help_text(primary_bot_username))
                continue

            command_arg = _extract_check_argument(text)
            if command_arg is not None:
                pizza_name = resolve_pizza_name(config, command_arg or None)
                state.set_last_pizza(chat_id, pizza_name)
                client.send_message(chat_id=chat_id, text=f"Проверяю Dodo для: {pizza_name}")
                try:
                    report = build_report(config, pizza_name=pizza_name)
                except (DodoHTTPError, RuntimeError) as exc:
                    report = f"{CHECK_FAILED_PREFIX}{exc}"
                for chunk in _split_message(report):
                    client.send_message(chat_id=chat_id, text=chunk)
                continue

            nearby_arg = _extract_nearby_argument(text)
            if nearby_arg is not None and user_id:
                pizza_name = _resolve_nearby_pizza_name(config, state, chat_id, nearby_arg)
                if pizza_name is None:
                    client.send_message(
                        chat_id=chat_id,
                        text=_render_template_text(LOCATION_REQUEST_NEEDS_PIZZA_TEXT, primary_bot_username),
                    )
                    continue
                state.set_last_pizza(chat_id, pizza_name)
                state.set_pending_location_request(chat_id, user_id, pizza_name)
                client.send_message(
                    chat_id=chat_id,
                    text=f"Ищу ближайшие точки для '{pizza_name}'. {LOCATION_REQUEST_TEXT}",
                )
                continue

            mention_query = _extract_bot_mention_query(text, bot_usernames)
            if mention_query is not None and user_id:
                pizza_name = _resolve_mention_pizza_name(config, state, chat_id, mention_query)
                if pizza_name is None:
                    client.send_message(
                        chat_id=chat_id,
                        text=_render_template_text(LOCATION_REQUEST_NEEDS_PIZZA_TEXT, primary_bot_username),
                    )
                    continue
                state.set_last_pizza(chat_id, pizza_name)
                state.set_pending_location_request(chat_id, user_id, pizza_name)
                client.send_message(
                    chat_id=chat_id,
                    text=f"Ищу ближайшие точки для '{pizza_name}'. {LOCATION_REQUEST_TEXT}",
                )
                continue

            command, _ = _parse_command(text)
            if command:
                client.send_message(
                    chat_id=chat_id,
                    text=_render_template_text(UNKNOWN_COMMAND_TEXT, primary_bot_username),
                )

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


def _extract_nearby_argument(text: str) -> str | None:
    command, argument = _parse_command(text)
    if command not in NEARBY_COMMANDS:
        return None
    return argument


def _extract_bot_mention_query(text: str, bot_usernames: list[str] | tuple[str, ...] | None) -> str | None:
    if not bot_usernames:
        return None

    cleaned_text = text
    matched = False
    for bot_username in bot_usernames:
        pattern = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
        if pattern.search(cleaned_text):
            cleaned_text = pattern.sub(" ", cleaned_text)
            matched = True
    if not matched:
        return None
    return _cleanup_free_text(cleaned_text)


def _resolve_mention_pizza_name(
    config: dict,
    state: BotState,
    chat_id: str,
    mention_query: str,
) -> str | None:
    if not mention_query or _looks_like_nearby_request(mention_query):
        last_pizza = state.get_last_pizza(chat_id)
        if last_pizza:
            return last_pizza
        try:
            return resolve_pizza_name(config)
        except RuntimeError:
            return None
    return mention_query


def _resolve_nearby_pizza_name(
    config: dict,
    state: BotState,
    chat_id: str,
    command_arg: str,
) -> str | None:
    if command_arg:
        return command_arg

    last_pizza = state.get_last_pizza(chat_id)
    if last_pizza:
        return last_pizza
    try:
        return resolve_pizza_name(config)
    except RuntimeError:
        return None


def _looks_like_nearby_request(text: str) -> bool:
    normalized = _cleanup_free_text(text).casefold()
    if not normalized:
        return True
    keywords = [
        "где",
        "заказать",
        "рядом",
        "ближай",
        "поблизости",
        "локац",
        "гео",
        "геопози",
        "near",
        "nearby",
        "location",
    ]
    return any(keyword in normalized for keyword in keywords)


def _cleanup_free_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t\r\n,.:;!?-")


def _resolve_bot_usernames(client: TelegramClient, config: dict) -> list[str]:
    usernames: list[str] = []
    configured_username = str(config.get("telegram_bot_username") or "").strip().lstrip("@")
    try:
        me = client.get_me()
    except RuntimeError:
        actual_username = ""
    else:
        actual_username = str(me.get("username") or "").strip().lstrip("@")

    for username in [actual_username, configured_username]:
        if username and username not in usernames:
            usernames.append(username)
    return usernames


def _render_help_text(bot_username: str | None) -> str:
    return _render_template_text(HELP_TEXT, bot_username)


def _render_template_text(text: str, bot_username: str | None) -> str:
    placeholder = f"@{bot_username}" if bot_username else "@botname"
    return text.replace("@botname", placeholder)


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
