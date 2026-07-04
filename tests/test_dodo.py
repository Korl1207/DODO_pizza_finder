import unittest

from dodo_parser.dodo import find_products, parse_products


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


if __name__ == "__main__":
    unittest.main()
