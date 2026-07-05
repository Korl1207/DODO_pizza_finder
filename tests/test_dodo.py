import unittest

from dodo_parser.dodo import (
    build_stop_list_lookup,
    find_products,
    menu_match_allows_add_to_cart,
    parse_products,
    product_page_allows_add_to_cart,
)


class DodoParserTests(unittest.TestCase):
    def test_parse_products_from_links(self) -> None:
        html = """
        <a href="/moscow/product/pizza-pepperoni">Пепперони</a>
        <a href="/moscow/product/pizza-margarita">Маргарита</a>
        <a href="/spb/product/pizza-pepperoni">Не тот город</a>
        """

        products = parse_products(html, "moscow")

        self.assertEqual([product.name for product in products], ["Пепперони", "Маргарита"])

    def test_find_products_case_insensitive(self) -> None:
        products = parse_products(
            '<a href="/moscow/product/pizza-pepperoni">Пепперони фреш</a>',
            "moscow",
        )

        matches = find_products(products, "пепперони")

        self.assertEqual(len(matches), 1)

    def test_find_products_ignores_leading_pizza_word(self) -> None:
        products = parse_products(
            '<a href="/moscow/product/picca-enchantiks">Энчантикс</a>',
            "moscow",
        )

        matches = find_products(products, "Пицца Энчантикс")

        self.assertEqual(len(matches), 1)

    def test_product_page_allows_add_to_cart_detects_available_product(self) -> None:
        html = """
        <div class="product">
            <button data-testid="button_add_to_cart" type="button">В корзину за 819 ₽</button>
        </div>
        """

        self.assertTrue(product_page_allows_add_to_cart(html))

    def test_product_page_allows_add_to_cart_rejects_disabled_button(self) -> None:
        html = """
        <div class="product">
            <button data-testid="button_add_to_cart" type="button" disabled>В корзину</button>
        </div>
        """

        self.assertFalse(product_page_allows_add_to_cart(html))

    def test_product_page_allows_add_to_cart_rejects_sold_out_product(self) -> None:
        html = """
        <div class="product">
            <p>Пиццу раскупили, добавить в корзину нельзя</p>
            <button data-testid="button_add_to_cart" type="button">В корзину</button>
        </div>
        """

        self.assertFalse(product_page_allows_add_to_cart(html))


    def test_build_stop_list_lookup_normalizes_ids(self) -> None:
        stop_list_lookup = build_stop_list_lookup(
            {
                "productUUIds": ["ABC-123", "def-456"],
                "toppingUUIds": ["TOP-1"],
            }
        )

        self.assertEqual(stop_list_lookup, {"abc-123", "def-456", "top-1"})

    def test_menu_match_allows_add_to_cart_rejects_default_stopped_variation(self) -> None:
        match = {
            "name": "Пицца Энчантикс",
            "defaultProductId": "product-default",
            "variationProductIds": ["product-default", "product-large"],
        }

        self.assertFalse(menu_match_allows_add_to_cart(match, {"product-default"}))

    def test_menu_match_allows_add_to_cart_rejects_meta_product_when_all_variations_stopped(self) -> None:
        match = {
            "name": "Пицца Энчантикс",
            "defaultProductId": "product-default",
            "variationProductIds": ["product-default", "product-large"],
        }

        self.assertFalse(
            menu_match_allows_add_to_cart(match, {"product-default", "product-large"})
        )

    def test_menu_match_allows_add_to_cart_keeps_product_when_other_variation_is_available(self) -> None:
        match = {
            "name": "Пицца Энчантикс",
            "defaultProductId": "product-large",
            "variationProductIds": ["product-small", "product-large"],
        }

        self.assertTrue(menu_match_allows_add_to_cart(match, {"product-small"}))


if __name__ == "__main__":
    unittest.main()
