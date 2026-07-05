from __future__ import annotations

import json
from pathlib import Path

from .distance import DEFAULT_DISTANCE_API_URL, DistanceAPIError, DistanceMatrixClient
from .dodo import DodoClient, DodoHTTPError, PizzeriaResult

DEFAULT_PIZZERIA_PREVIEW_LIMIT = 5


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_pizza_name(config: dict, override: str | None = None) -> str:
    if override is not None and override.strip():
        return override.strip()

    pizza_name = str(config.get("pizza_name") or "").strip()
    if not pizza_name:
        raise RuntimeError("pizza_name must be set in config.json or passed as an override")
    return pizza_name


def create_dodo_client(config: dict) -> DodoClient:
    return DodoClient(
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


def build_report(config: dict, pizza_name: str | None = None) -> str:
    client = create_dodo_client(config)
    pizza_name = resolve_pizza_name(config, pizza_name)
    preview_limit = max(1, int(config.get("pizzeria_preview_limit", DEFAULT_PIZZERIA_PREVIEW_LIMIT) or 5))
    lines = [f"Dodo Pizza: проверка '{pizza_name}'"]

    city_result = None
    if config.get("check_city_menu", True):
        city_result = client.check_city_menu(pizza_name)
        lines.append(
            "Городское меню: "
            f"{'позиция есть в каталоге' if city_result.found else 'позиция не найдена в каталоге'}"
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
                for result in found_results[:preview_limit]:
                    if result.url:
                        lines.append(f"- {result.pizzeria_name}: {result.url}")
                    else:
                        lines.append(f"- {result.pizzeria_name}")
                if len(found_results) > preview_limit:
                    lines.append(f"Показываю первые {preview_limit} точек из {len(found_results)}.")
            else:
                if city_result and city_result.found:
                    lines.append(
                        "Позиция есть в каталоге Dodo, но сейчас не нашел ни одной точки, "
                        "где ее можно добавить в корзину."
                    )
                else:
                    lines.append("Не нашел ни одной точки с этой пиццей прямо сейчас.")

            if config.get("show_missing_pizzerias", False):
                missing_results = [result for result in pizzeria_results if not result.found]
                lines.append("")
                lines.append(f"Кафе без этой пиццы: {len(missing_results)}")
                for result in missing_results:
                    lines.append(f"- {result.pizzeria_name}")

    return "\n".join(lines)


def build_nearby_report(
    config: dict,
    *,
    latitude: float,
    longitude: float,
    pizza_name: str | None = None,
) -> str:
    client = create_dodo_client(config)
    pizza_name = resolve_pizza_name(config, pizza_name)
    limit = max(1, int(config.get("nearby_results_limit", 10) or 10))

    try:
        pizzeria_results = client.check_pizzerias(pizza_name)
    except DodoHTTPError as exc:
        return f"Не получилось проверить пиццерии для '{pizza_name}': {exc}"

    available_with_coordinates = [
        result
        for result in pizzeria_results
        if result.found and result.latitude is not None and result.longitude is not None
    ]
    if not available_with_coordinates:
        found_without_coordinates = [result for result in pizzeria_results if result.found]
        if found_without_coordinates:
            return (
                f"Нашёл пиццу '{pizza_name}', но не смог получить координаты пиццерий "
                "для расчёта расстояния."
            )
        return f"Не нашёл ни одной открытой пиццерии, где сейчас можно заказать '{pizza_name}'."

    routing_client = DistanceMatrixClient(
        base_url=str(config.get("distance_api_url") or DEFAULT_DISTANCE_API_URL),
        profile=str(config.get("distance_api_profile") or "driving"),
        batch_size=int(config.get("distance_api_batch_size", 25) or 25),
    )
    try:
        distances = routing_client.get_distances(
            origin_latitude=latitude,
            origin_longitude=longitude,
            destinations=[
                (result.latitude, result.longitude)
                for result in available_with_coordinates
                if result.latitude is not None and result.longitude is not None
            ],
        )
    except DistanceAPIError as exc:
        return f"Не получилось посчитать расстояния до пиццерий: {exc}"

    nearby: list[tuple[PizzeriaResult, float, float]] = []
    for result, route in zip(available_with_coordinates, distances):
        if route is None:
            continue
        nearby.append((result, route.distance_meters, route.duration_seconds))

    if not nearby:
        return f"Нашёл '{pizza_name}', но routing API не вернул расстояния до доступных пиццерий."

    nearby.sort(key=lambda item: (item[1], item[2], item[0].pizzeria_name.casefold()))
    lines = [f"Ближайшие пиццерии с '{pizza_name}' рядом с вашей геопозицией:"]
    for index, (result, distance_meters, duration_seconds) in enumerate(nearby[:limit], start=1):
        address = f" ({result.address})" if result.address and result.address not in result.pizzeria_name else ""
        suffix = f" - {_format_distance(distance_meters)}, ~{_format_duration(duration_seconds)}"
        if result.url:
            lines.append(f"{index}. {result.pizzeria_name}{address}{suffix} - {result.url}")
        else:
            lines.append(f"{index}. {result.pizzeria_name}{address}{suffix}")

    if len(nearby) > limit:
        lines.append("")
        lines.append(f"Показываю первые {limit} из {len(nearby)} подходящих пиццерий.")

    return "\n".join(lines)


def _format_distance(distance_meters: float) -> str:
    if distance_meters >= 1000:
        return f"{distance_meters / 1000:.1f} км"
    return f"{int(round(distance_meters))} м"


def _format_duration(duration_seconds: float) -> str:
    minutes = max(1, int(round(duration_seconds / 60)))
    return f"{minutes} мин"
