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
ADD_TO_CART_BUTTON_RE = re.compile(r'data-testid=["\']button_add_to_cart["\'][^>]*>', re.IGNORECASE)
DISABLED_ADD_TO_CART_BUTTON_RE = re.compile(
    r'data-testid=["\']button_add_to_cart["\'][^>]*\sdisabled(?:\s|=|>)',
    re.IGNORECASE,
)
UNAVAILABLE_PRODUCT_PAGE_RE = re.compile(
    r"(?:\u0440\u0430\u0441\u043a\u0443\u043f|\u043d\u0435\u0442\s+\u0432\s+\u043d\u0430\u043b\u0438\u0447\u0438\u0438|"
    r"\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f|\u0437\u0430\u043a\u043e\u043d\u0447\u0438\u043b)",
    re.IGNORECASE,
)


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
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


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
                    address=format_pizzeria_address(pizzeria.get("address")),
                    latitude=get_pizzeria_latitude(pizzeria),
                    longitude=get_pizzeria_longitude(pizzeria),
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

                pizzerias_url = f"{BASE_URL}/api/pizzerias?{urlencode({'localityId': self.locality_id})}"
                try:
                    pizzerias = self._request_json_with_page(page, pizzerias_url)
                except DodoHTTPError:
                    pizzerias = self._request_json_with_context(context, pizzerias_url)
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
                            "address": format_pizzeria_address(pizzeria.get("address")) or "",
                            "latitude": get_pizzeria_latitude(pizzeria),
                            "longitude": get_pizzeria_longitude(pizzeria),
                            "menuUrl": self._pizzeria_menu_url(str(pizzeria_id)),
                        }
                    )

                checked = page.evaluate(
                    """
                    async ({ targets, pizzaName, countryCode, culture, concurrency }) => {
                        const addToCartButtonPattern = /data-testid=["']button_add_to_cart["'][^>]*>/i;
                        const disabledAddToCartButtonPattern =
                            /data-testid=["']button_add_to_cart["'][^>]*\\sdisabled(?:\\s|=|>)/i;
                        const unavailableProductPattern =
                            /(?:раскуп|нет\\s+в\\s+наличии|недоступ|закончился)/i;
                        const normalize = (value) =>
                            String(value || "")
                                .toLocaleLowerCase("ru-RU")
                                .replace(/ё/g, "е")
                                .replace(/[^\\p{L}\\p{N}_\\s-]+/gu, " ")
                                .replace(/\\s+/g, " ")
                                .trim();
                        const readAdditionalDataValue = (entries, key) => {
                            if (!Array.isArray(entries)) return "";
                            const entry = entries.find(
                                (item) =>
                                    item &&
                                    typeof item === "object" &&
                                    item.key === key &&
                                    typeof item.value === "string" &&
                                    item.value.trim()
                            );
                            return entry ? entry.value.trim() : "";
                        };
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
                        const collectMenuMatches = (menu) => {
                            if (!menu || typeof menu !== "object" || !Array.isArray(menu.items)) {
                                return [];
                            }
                            const seen = new Set();
                            const exactMatches = [];
                            const partialMatches = [];
                            for (const item of menu.items) {
                                if (!item || typeof item !== "object" || typeof item.name !== "string") {
                                    continue;
                                }
                                if (!matchesQuery(item.name)) {
                                    continue;
                                }
                                const slug = readAdditionalDataValue(item.additionalData, "TranslitName");
                                const key = `${normalize(item.name)}::${slug}`;
                                if (seen.has(key)) {
                                    continue;
                                }
                                seen.add(key);
                                const variationProductIds = Array.isArray(item.variations)
                                    ? item.variations
                                          .map((variation) => variation?.product?.id)
                                          .filter((productId) => typeof productId === "string" && productId.trim())
                                    : [];
                                const defaultProductId =
                                    (Array.isArray(item.variations)
                                        ? item.variations.find(
                                              (variation) =>
                                                  variation &&
                                                  typeof variation === "object" &&
                                                  variation.isDefault &&
                                                  variation.product &&
                                                  typeof variation.product.id === "string" &&
                                                  variation.product.id.trim()
                                          )?.product?.id
                                        : "") ||
                                    variationProductIds[0] ||
                                    "";
                                const match = {
                                    name: item.name,
                                    slug,
                                    defaultProductId,
                                    variationProductIds: [...new Set(variationProductIds)],
                                };
                                if (queryTerms.some((term) => term && normalize(item.name) === term)) {
                                    exactMatches.push(match);
                                } else {
                                    partialMatches.push(match);
                                }
                            }
                            return exactMatches.length > 0 ? exactMatches : partialMatches;
                        };
                        const buildProductUrl = (target, slug) => {
                            const baseUrl = String(target.url || "").replace(/\\/$/, "");
                            if (!baseUrl || !slug) {
                                return "";
                            }
                            return `${baseUrl}/product/${slug}`;
                        };
                        const productPageAllowsAddToCart = (html) =>
                            addToCartButtonPattern.test(html) &&
                            !disabledAddToCartButtonPattern.test(html) &&
                            !unavailableProductPattern.test(html);
                        const fetchProductAvailability = async (productUrl) => {
                            const response = await fetch(productUrl, {
                                credentials: "include",
                                headers: {
                                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                },
                            });
                            if (!response.ok) {
                                return false;
                            }
                            const html = await response.text();
                            return productPageAllowsAddToCart(html);
                        };
                        const fetchStopLists = async (target, fallbackReferer) => {
                            const referer = String(target.url || fallbackReferer || "").trim();
                            if (!referer) {
                                return null;
                            }
                            const response = await fetch("/api/workflow/actualize", {
                                method: "POST",
                                credentials: "include",
                                headers: {
                                    "Accept": "application/json",
                                    "X-Requested-With": "XMLHttpRequest",
                                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                },
                                body: new URLSearchParams({ referer }).toString(),
                            });
                            if (!response.ok) {
                                return null;
                            }
                            const workflow = await response.json();
                            if (!workflow || typeof workflow !== "object") {
                                return null;
                            }
                            const stopLists = workflow.stopLists;
                            if (!stopLists || typeof stopLists !== "object") {
                                return { productUUIds: [], toppingUUIds: [] };
                            }
                            return stopLists;
                        };
                        const checkOne = async (target) => {
                            const response = await fetch(target.menuUrl, {
                                credentials: "include",
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
                            const menuMatches = collectMenuMatches(menu);
                            if (menuMatches.length === 0) {
                                return {
                                    ...target,
                                    found: false,
                                    matches: [],
                                    stopLists: { productUUIds: [], toppingUUIds: [] },
                                    matchesAreFinal: true,
                                };
                            }

                            const fallbackReferer = buildProductUrl(target, menuMatches[0]?.slug);
                            const stopLists = await fetchStopLists(target, fallbackReferer);
                            if (stopLists) {
                                return {
                                    ...target,
                                    found: true,
                                    matches: menuMatches,
                                    stopLists,
                                    matchesAreFinal: false,
                                };
                            }

                            const availableMatches = [];
                            for (const match of menuMatches) {
                                const productUrl = buildProductUrl(target, match.slug);
                                if (!productUrl) {
                                    continue;
                                }
                                if (await fetchProductAvailability(productUrl)) {
                                    availableMatches.push(match);
                                }
                            }
                            return {
                                ...target,
                                found: availableMatches.length > 0,
                                matches: availableMatches,
                                stopLists: null,
                                matchesAreFinal: true,
                            };
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
                        "concurrency": 4,
                    },
                )

                results: list[PizzeriaResult] = []
                for item in checked:
                    raw_matches = item.get("matches") or []
                    if item.get("matchesAreFinal"):
                        available_matches = [
                            str(match.get("name"))
                            for match in raw_matches
                            if isinstance(match, dict) and match.get("name")
                        ]
                    else:
                        stop_list_lookup = build_stop_list_lookup(item.get("stopLists"))
                        available_matches = [
                            str(match.get("name"))
                            for match in raw_matches
                            if isinstance(match, dict)
                            and match.get("name")
                            and menu_match_allows_add_to_cart(match, stop_list_lookup)
                        ]

                    results.append(
                        PizzeriaResult(
                            pizzeria_name=str(item["name"]),
                            pizzeria_id=str(item["id"]),
                            found=bool(available_matches),
                            matches=list(dict.fromkeys(available_matches)),
                            url=str(item["url"]) if item.get("url") else None,
                            address=str(item["address"]) if item.get("address") else None,
                            latitude=parse_coordinate_value(item.get("latitude")),
                            longitude=parse_coordinate_value(item.get("longitude")),
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

    def _request_json_with_page(self, page: Any, url: str) -> Any:
        try:
            payload = page.evaluate(
                """
                async ({ url, countryCode, culture }) => {
                    const response = await fetch(url, {
                        credentials: "include",
                        headers: {
                            "Accept": "application/json",
                            "CountryCode": countryCode,
                            "LanguageCode": culture,
                        },
                    });
                    const text = await response.text();
                    return { ok: response.ok, status: response.status, text };
                }
                """,
                {
                    "url": url,
                    "countryCode": self.country_code,
                    "culture": self.culture,
                },
            )
        except Exception as exc:
            raise DodoHTTPError(f"{url} request failed in browser page: {exc}") from exc

        if not isinstance(payload, dict):
            raise DodoHTTPError(f"{url} returned an unexpected browser payload")

        status = int(payload.get("status", 0) or 0)
        if not payload.get("ok"):
            raise DodoHTTPError(f"{url} returned HTTP {status}")

        text = payload.get("text")
        if not isinstance(text, str):
            raise DodoHTTPError(f"{url} did not return text")

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


def normalize_stop_list_id(value: Any) -> str:
    return str(value or "").strip().lower()


def build_stop_list_lookup(stop_lists: Any) -> set[str]:
    if not isinstance(stop_lists, dict):
        return set()

    lookup: set[str] = set()
    for key in ("productUUIds", "toppingUUIds"):
        values = stop_lists.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            normalized = normalize_stop_list_id(value)
            if normalized:
                lookup.add(normalized)
    return lookup


def menu_match_allows_add_to_cart(match: Any, stop_list_lookup: set[str]) -> bool:
    if not isinstance(match, dict) or not stop_list_lookup:
        return True

    variation_product_ids = []
    for product_id in match.get("variationProductIds") or []:
        normalized = normalize_stop_list_id(product_id)
        if normalized:
            variation_product_ids.append(normalized)

    default_product_id = normalize_stop_list_id(match.get("defaultProductId"))
    if default_product_id and default_product_id in stop_list_lookup:
        return False
    if variation_product_ids and all(product_id in stop_list_lookup for product_id in variation_product_ids):
        return False
    return True


def product_page_allows_add_to_cart(html: str) -> bool:
    if not ADD_TO_CART_BUTTON_RE.search(html):
        return False
    if DISABLED_ADD_TO_CART_BUTTON_RE.search(html):
        return False
    return not UNAVAILABLE_PRODUCT_PAGE_RE.search(html)


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


def get_pizzeria_latitude(pizzeria: dict[str, Any]) -> float | None:
    latitude, _ = get_pizzeria_coordinates(pizzeria)
    return latitude


def get_pizzeria_longitude(pizzeria: dict[str, Any]) -> float | None:
    _, longitude = get_pizzeria_coordinates(pizzeria)
    return longitude


def get_pizzeria_coordinates(pizzeria: dict[str, Any]) -> tuple[float | None, float | None]:
    candidates = [
        pizzeria.get("coordinates"),
        pizzeria.get("coordinate"),
        pizzeria.get("location"),
        pizzeria.get("position"),
        pizzeria.get("point"),
        pizzeria.get("geoPosition"),
        pizzeria.get("geoPoint"),
        pizzeria.get("address"),
    ]
    for candidate in candidates:
        latitude, longitude = parse_coordinate_pair(candidate)
        if latitude is not None and longitude is not None:
            return latitude, longitude
    return None, None


def parse_coordinate_pair(value: Any) -> tuple[float | None, float | None]:
    if isinstance(value, dict):
        latitude = parse_coordinate_value(
            pick_first(value, ["latitude", "lat", "Latitude", "Lat", "y", "Y"])
        )
        longitude = parse_coordinate_value(
            pick_first(value, ["longitude", "lng", "lon", "Longitude", "Lng", "Lon", "x", "X"])
        )
        if latitude is not None and longitude is not None:
            return latitude, longitude

        coordinates = value.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            longitude = parse_coordinate_value(coordinates[0])
            latitude = parse_coordinate_value(coordinates[1])
            if latitude is not None and longitude is not None:
                return latitude, longitude
    return None, None


def parse_coordinate_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
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
