from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def notify_telegram(*, token: str, chat_id: str, text: str) -> None:
    TelegramClient(token=token).send_message(chat_id=chat_id, text=text)


class TelegramClient:
    def __init__(self, *, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._request("sendMessage", payload)

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        data = self._request("getUpdates", payload)
        result = data.get("result", [])
        if not isinstance(result, list):
            raise RuntimeError("Telegram returned an unexpected getUpdates response")
        return result

    def get_me(self) -> dict[str, Any]:
        data = self._request("getMe", {})
        result = data.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError("Telegram returned an unexpected getMe response")
        return result

    def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{method}"
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=payload.get("timeout", 20) + 5) as response:
                text = response.read().decode("utf-8")
        except HTTPError as exc:
            raise RuntimeError(f"Telegram returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Telegram request failed: {exc.reason}") from exc

        data = json.loads(text)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram returned an error: {data}")
        return data
