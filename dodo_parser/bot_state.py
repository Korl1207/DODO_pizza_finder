from __future__ import annotations

import json
import time
from pathlib import Path


class BotState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_last_pizza(self, chat_id: str) -> str | None:
        data = self._load()
        value = data.get("last_pizza_by_chat", {}).get(str(chat_id))
        return str(value).strip() if value else None

    def set_last_pizza(self, chat_id: str, pizza_name: str) -> None:
        data = self._load()
        data.setdefault("last_pizza_by_chat", {})[str(chat_id)] = pizza_name
        self._save(data)

    def set_pending_location_request(self, chat_id: str, user_id: str, pizza_name: str) -> None:
        data = self._load()
        data.setdefault("pending_location_requests", {})[self._pending_key(chat_id, user_id)] = {
            "pizza_name": pizza_name,
            "requested_at": int(time.time()),
        }
        self._save(data)

    def pop_pending_location_request(
        self,
        chat_id: str,
        user_id: str,
        *,
        max_age_seconds: int,
    ) -> str | None:
        data = self._load()
        pending_requests = data.setdefault("pending_location_requests", {})
        key = self._pending_key(chat_id, user_id)
        pending = pending_requests.get(key)
        if not isinstance(pending, dict):
            return None

        requested_at = int(pending.get("requested_at", 0) or 0)
        if requested_at <= 0 or int(time.time()) - requested_at > max_age_seconds:
            pending_requests.pop(key, None)
            self._save(data)
            return None

        pending_requests.pop(key, None)
        self._save(data)
        pizza_name = str(pending.get("pizza_name") or "").strip()
        return pizza_name or None

    def _load(self) -> dict:
        if not self.path.exists():
            return {"last_pizza_by_chat": {}, "pending_location_requests": {}}

        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {"last_pizza_by_chat": {}, "pending_location_requests": {}}
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)

    @staticmethod
    def _pending_key(chat_id: str, user_id: str) -> str:
        return f"{chat_id}:{user_id}"
