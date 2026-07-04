from __future__ import annotations

import json
from pathlib import Path

from .dodo import DodoClient, DodoHTTPError


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_report(config: dict) -> str:
    client = DodoClient(
        city=config.get("city", "moscow"),
        country_code=config.get("country_code", "RU"),
        country_id=config.get("country_id"),
        culture=config.get("culture", "ru-RU"),
        locality_id=config.get("locality_id"),
        api_version=config.get("api_version", "v1"),
        menu_type=config.get("menu_type", "delivery"),
        fetch_mode=config.get("fetch_mode", "auto"),
        only_open_pizzerias=config.get("only_open_pizzerias", True),
    )

    pizza_name = config["pizza_name"]
    lines = [f"Dodo Pizza: проверка '{pizza_name}'"]

    if config.get("check_city_menu", True):
        city_result = client.check_city_menu(pizza_name)
        lines.append(
            f"Городское меню: {'найдена' if city_result.found else 'не найдена'}"
        )

        if city_result.matches:
            for product in city_result.matches:
                lines.append(f"- {product.name}: {product.url}")

    if config.get("check_pizzerias", False):
        try:
            pizzeria_results = client.check_pizzerias(pizza_name)
        except DodoHTTPError as exc:
            lines.append("")
            lines.append(f"Проверка по кафе не выполнена: {exc}")
        else:
            found_results = [result for result in pizzeria_results if result.found]
            lines.append("")
            lines.append(f"Кафе, где сейчас есть '{pizza_name}': {len(found_results)}")
            if found_results:
                for result in found_results:
                    if result.url:
                        lines.append(f"- {result.pizzeria_name}: {result.url}")
                    else:
                        lines.append(f"- {result.pizzeria_name}")
            else:
                lines.append("Не нашел ни одной точки с этой пиццей прямо сейчас.")

            if config.get("show_missing_pizzerias", False):
                missing_results = [result for result in pizzeria_results if not result.found]
                lines.append("")
                lines.append(f"Кафе без этой пиццы: {len(missing_results)}")
                for result in missing_results:
                    lines.append(f"- {result.pizzeria_name}")

    return "\n".join(lines)
