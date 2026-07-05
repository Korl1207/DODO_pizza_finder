import unittest

from dodo_parser.report import resolve_pizza_name


class ReportConfigTests(unittest.TestCase):
    def test_resolve_pizza_name_uses_config_by_default(self) -> None:
        pizza_name = resolve_pizza_name({"pizza_name": "Пепперони"})

        self.assertEqual(pizza_name, "Пепперони")

    def test_resolve_pizza_name_uses_override_when_provided(self) -> None:
        pizza_name = resolve_pizza_name({"pizza_name": "Энчантикс"}, "Пепперони")

        self.assertEqual(pizza_name, "Пепперони")

    def test_resolve_pizza_name_trims_values(self) -> None:
        pizza_name = resolve_pizza_name({"pizza_name": "  Энчантикс  "}, "  ")

        self.assertEqual(pizza_name, "Энчантикс")

    def test_resolve_pizza_name_requires_non_empty_value(self) -> None:
        with self.assertRaises(RuntimeError):
            resolve_pizza_name({"pizza_name": "  "})


if __name__ == "__main__":
    unittest.main()
