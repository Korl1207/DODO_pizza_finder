from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://dodopizza.ru"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
}


class DodoHTTPError(RuntimeError):
    """Raised when Dodo blocks or rejects a request."""


@dataclass(frozen=True)
class Product:
    name: str
    url: str


@dataclass(frozen=True)
class CityMenuResult:
    found: bool
    matches: list[Product]


@dataclass(frozen=True)
class PizzeriaResult:
    pizzeria_name: str
    pizzeria_id: str
    found: bool
    matches: list[str]
    url: str | None = None


class ProductLinkParser(HTMLParser):
    def __init__(self, city: str) -> None:
        super().__init__()
        self.city = city.strip("/")
        self.products: list[Product] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href and f"/{self.city}/product/" in href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._current_href:
            return
        name = " ".join("".join(self._text_parts).split())
        if name:
            url = self._current_href
            if url.startswith("/"):
                url = f"{BASE_URL}{url}"
            self.products.append(Product(name=name, url=url))
        self._current_href = None
        self._text_parts = []


class DodoClient:
    def __init__(
        self,
        *,
        city: str,
        country_code: str,
        country_id: int | str | None = None,
        culture: str,
        locality_id: str | None,
        api_version: str,
        menu_type: str,
        fetch_mode: str = "auto",
        only_open_pizzerias: bool = True,
    ) -> None:
        self.city = city.strip("/")
        self.country_code = country_code
        self.country_id = str(country_id) if country_id else None
        self.culture = culture
        self.locality_id = locality_id
        self.api_version = api_version
        self.menu_type = menu_type
        self.fetch_mode = fetch_mode
        self.only_open_pizzerias = only_open_pizzerias

    def check_city_menu(self, pizza_name: str) -> CityMenuResult:
        html = self._get_city_html()
        products = parse_products(html, self.city)
        matches = find_products(products, pizza_name)
        return CityMenuResult(found=bool(matches), matches=matches)

    def _get_city_html(self) -> str:
        url = f"{BASE_URL}/{self.city}"
        if self.fetch_mode == "playwright":
            return self._get_rendered_html(url)

        html = self._get_text(url)
        if not looks_like_antibot_challenge(html):
            return html

        if self.fetch_mode == "http":
            raise DodoHTTPError("Dodo returned an anti-bot challenge instead of menu HTML")

        return self._get_rendered_html(url)

    def check_pizzerias(self, pizza_name: str) -> list[PizzeriaResult]:
        if not self.locality_id:
            raise DodoHTTPError("locality_id is required for per-pizzeria checks")

        if self.fetch_mode in {"auto", "playwright"}:
            return self._check_pizzerias_with_playwright(pizza_name)

        pizzerias = self.get_pizzerias()
        results: list[PizzeriaResult] = []
        for pizzeria in pizzerias:
            if self.only_open_pizzerias and pizzeria.get("isClosed"):
                continue
            pizzeria_id = get_pizzeria_id(pizzeria)
            pizzeria_name = get_pizzeria_name(pizzeria) or pizzeria_id
            if not pizzeria_id:
                continue

            menu = self.get_pizzeria_menu(str(pizzeria_id))
            names = extract_product_names(menu)
            terms = search_terms(pizza_name)
            matched_names = [name for name in names if text_matches_any(name, terms)]
            results.append(
                PizzeriaResult(
                    pizzeria_name=str(pizzeria_name),
                    pizzeria_id=str(pizzeria_id),
                    found=bool(matched_names),
                    matches=matched_names,
                    url=get_pizzeria_url(pizzeria),
                )
            )
        return results

    def _check_pizzerias_with_playwright(self, pizza_name: str) -> list[PizzeriaResult]:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DodoHTTPError(
                "Install browser mode with `python -m pip install -r requirements.txt` "
                "and `python -m playwright install chromium`."
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    locale=self.culture,
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                )
                page = context.new_page()
                page.goto(f"{BASE_URL}/{self.city}", wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_selector(
                    f'a[href*="/{self.city}/product/"]',
                    timeout=60_000,
                )

                pizzerias = self._request_json_with_context(
                    context,
                    f"{BASE_URL}/api/pizzerias?{urlencode({'localityId': self.locality_id})}",
                )
                if not isinstance(pizzerias, list):
                    raise DodoHTTPError(
                        f"Unexpected /api/pizzerias response: {type(pizzerias).__name__}"
                    )

                targets: list[dict[str, str]] = []
                for pizzeria in pizzerias:
                    if not isinstance(pizzeria, dict):
                        continue
                    if self.only_open_pizzerias and pizzeria.get("isClosed"):
                        continue
                    pizzeria_id = get_pizzeria_id(pizzeria)
                    pizzeria_name = get_pizzeria_name(pizzeria) or pizzeria_id
                    if not pizzeria_id:
                        continue

                    targets.append(
                        {
                            "id": str(pizzeria_id),
                            "name": str(pizzeria_name),
                            "url": get_pizzeria_url(pizzeria) or "",
                            "menuUrl": self._pizzeria_menu_url(str(pizzeria_id)),
                        }
                    )

                checked = page.evaluate(
                    """
                    async ({ targets, pizzaName, countryCode, culture, concurrency }) => {
                        const normalize = (value) =>
                            String(value || "")
                                .toLocaleLowerCase("ru-RU")
                                .replace(/ё/g, "е")
                                .replace(/[^\\p{L}\\p{N}_\\s-]+/gu, " ")
                                .replace(/\\s+/g, " ")
                                .trim();
                        const baseQuery = normalize(pizzaName);
                        const queryTerms = [baseQuery];
                        const withoutPizza = baseQuery.replace(/^пицца\\s+/, "").trim();
                        if (withoutPizza && withoutPizza !== baseQuery) queryTerms.push(withoutPizza);
                        const matchesQuery = (name) => {
                            const normalizedName = normalize(name);
                            return queryTerms.some((term) => term && normalizedName.includes(term));
                        };
                        const collectNames = (node, output = []) => {
                            if (Array.isArray(node)) {
                                for (const item of node) collectNames(item, output);
                            } else if (node && typeof node === "object") {
                                for (const [key, value] of Object.entries(node)) {
                                    if (["name", "title", "productName"].includes(key) && typeof value === "string") {
                                        output.push(value);
                                    } else {
                                        collectNames(value, output);
                                    }
                                }
                            }
                            return output;
                        };
                        const checkOne = async (target) => {
                            const response = await fetch(target.menuUrl, {
                                headers: {
                                    "Accept": "application/json",
                                    "CountryCode": countryCode,
                                    "LanguageCode": culture,
                                },
                            });
                            if (!response.ok) {
                                return { ...target, found: false, matches: [], error: response.status };
                            }
                            const menu = await response.json();
                            const names = [...new Set(collectNames(menu))];
                            const matches = names.filter(matchesQuery);
                            return { ...target, found: matches.length > 0, matches };
                        };

                        const results = new Array(targets.length);
                        let index = 0;
                        const workers = Array.from({ length: concurrency }, async () => {
                            while (index < targets.length) {
                                const current = index++;
                                results[current] = await checkOne(targets[current]);
                            }
                        });
                        await Promise.all(workers);
                        return results;
                    }
                    """,
                    {
                        "targets": targets,
                        "pizzaName": pizza_name,
                        "countryCode": self.country_code,
                        "culture": self.culture,
                        "concurrency": 8,
                    },
                )

                results: list[PizzeriaResult] = []
                for item in checked:
                    results.append(
                        PizzeriaResult(
                            pizzeria_name=str(item["name"]),
                            pizzeria_id=str(item["id"]),
                            found=bool(item["found"]),
                            matches=list(item.get("matches") or []),
                            url=str(item["url"]) if item.get("url") else None,
                        )
                    )

                browser.close()
                return results
        except PlaywrightTimeoutError as exc:
            raise DodoHTTPError("Playwright opened Dodo, but required data did not load") from exc

    def get_pizzerias(self) -> list[dict[str, Any]]:
        query = urlencode({"localityId": self.locality_id})
        data = self._get_json(f"{BASE_URL}/api/pizzerias?{query}")
        if not isinstance(data, list):
            raise DodoHTTPError(f"Unexpected /api/pizzerias response: {type(data).__name__}")
        return data

    def get_pizzeria_menu(self, pizzeria_id: str) -> dict[str, Any]:
        data = self._get_json(self._pizzeria_menu_url(pizzeria_id))
        if not isinstance(data, dict):
            raise DodoHTTPError(f"Unexpected menu response: {type(data).__name__}")
        return data

    def _pizzeria_menu_url(self, pizzeria_id: str) -> str:
        query = urlencode({"cultures": self.culture, "subcategoriesInMenu": "false"})
        return (
            f"{BASE_URL}/api/{self.api_version}/menu/{self.menu_type}"
            f"/countries/{self._country_path_code()}/pizzerias/{pizzeria_id.lower()}?{query}"
        )

    def _country_path_code(self) -> str:
        if self.country_id:
            return self.country_id
        if self.country_code.upper() == "RU":
            return "643"
        return self.country_code.lower()

    def _get_text(self, url: str) -> str:
        request = Request(url, headers=DEFAULT_HEADERS)
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise DodoHTTPError(f"{url} returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise DodoHTTPError(f"{url} failed: {exc.reason}") from exc

    def _get_json(self, url: str) -> Any:
        headers = {
            **DEFAULT_HEADERS,
            "Accept": "application/json",
            "CountryCode": self.country_code,
            "LanguageCode": self.culture,
        }
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise DodoHTTPError(
                f"{url} returned HTTP {exc.code}. "
                "Dodo may require browser cookies/headers for this endpoint."
            ) from exc
        except URLError as exc:
            raise DodoHTTPError(f"{url} failed: {exc.reason}") from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise DodoHTTPError(f"{url} did not return JSON") from exc

    def _request_json_with_context(self, context: Any, url: str) -> Any:
        try:
            response = context.request.get(
                url,
                headers={
                    "Accept": "application/json",
                    "CountryCode": self.country_code,
                    "LanguageCode": self.culture,
                },
                timeout=60_000,
            )
        except Exception as exc:
            raise DodoHTTPError(f"{url} request failed: {exc}") from exc

        if response.status >= 400:
            raise DodoHTTPError(f"{url} returned HTTP {response.status}")
        try:
            return response.json()
        except Exception as exc:
            raise DodoHTTPError(f"{url} did not return JSON") from exc

    def _get_rendered_html(self, url: str) -> str:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DodoHTTPError(
                "Dodo returned an anti-bot challenge. Install browser mode with "
                "`python -m pip install -r requirements.txt` and "
                "`python -m playwright install chromium`."
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(
                    locale=self.culture,
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                )
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_selector(
                    f'a[href*="/{self.city}/product/"]',
                    timeout=60_000,
                )
                html = page.content()
                browser.close()
                return html
        except PlaywrightTimeoutError as exc:
            raise DodoHTTPError("Playwright opened Dodo, but product links did not load") from exc


def parse_products(html: str, city: str) -> list[Product]:
    if looks_like_antibot_challenge(html):
        raise DodoHTTPError("Dodo returned an anti-bot challenge instead of menu HTML")

    parser = ProductLinkParser(city)
    parser.feed(html)
    seen: set[tuple[str, str]] = set()
    products: list[Product] = []
    for product in parser.products:
        key = (normalize(product.name), product.url)
        if key not in seen:
            seen.add(key)
            products.append(product)
    return products


def find_products(products: list[Product], query: str) -> list[Product]:
    query_terms = search_terms(query)
    return [
        product
        for product in products
        if text_matches_any(product.name, query_terms)
    ]


def normalize(value: str) -> str:
    normalized = value.casefold().replace("ё", "е")
    normalized = re.sub(r"[^\w\s-]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def search_terms(value: str) -> list[str]:
    base = normalize(value)
    terms = [base]
    without_pizza = re.sub(r"^пицца\s+", "", base).strip()
    if without_pizza and without_pizza != base:
        terms.append(without_pizza)
    return [term for term in dict.fromkeys(terms) if term]


def text_matches_any(value: str, terms: list[str]) -> bool:
    normalized_value = normalize(value)
    return any(term in normalized_value for term in terms)


def pick_first(mapping: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def get_pizzeria_id(pizzeria: dict[str, Any]) -> str | None:
    value = pick_first(
        pizzeria,
        ["uuid", "uuId", "id", "pizzeriaId", "unitId", "restaurantId"],
    )
    return str(value) if value else None


def get_pizzeria_name(pizzeria: dict[str, Any]) -> str | None:
    name = pick_first(pizzeria, ["alias", "title", "name"])
    address = format_pizzeria_address(pizzeria.get("address"))
    if name and address and address not in str(name):
        return f"{name}: {address}"
    if name:
        return str(name)
    if address:
        return address
    return None


def get_pizzeria_url(pizzeria: dict[str, Any]) -> str | None:
    menu_route = pizzeria.get("menuRoute")
    if isinstance(menu_route, dict):
        url = menu_route.get("url")
        if isinstance(url, str) and url:
            return f"{BASE_URL}{url}" if url.startswith("/") else url
    return None


def format_pizzeria_address(address: Any) -> str | None:
    if not isinstance(address, dict):
        return str(address) if address else None

    full_address = address.get("fullAddress")
    if isinstance(full_address, str) and full_address:
        return full_address

    street = address.get("street")
    house = address.get("houseNumber")
    if isinstance(street, dict):
        locality = street.get("localityName")
        street_name = street.get("name")
        street_type = street.get("shortStreetTypeName")
        parts = []
        if locality:
            parts.append(str(locality))
        street_text = " ".join(str(part).strip() for part in [street_type, street_name] if part)
        if street_text:
            parts.append(street_text)
        if house:
            parts.append(str(house))
        return ", ".join(parts) if parts else None

    return None


def extract_product_names(value: Any) -> list[str]:
    names: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"name", "title", "productName"} and isinstance(child, str):
                    names.append(child)
                else:
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return sorted(set(names))


def looks_like_antibot_challenge(html: str) -> bool:
    markers = ["servicepipe", "Forbidden", "If you are not a bot", "/exhkqyad"]
    folded = html.casefold()
    return any(marker.casefold() in folded for marker in markers)
