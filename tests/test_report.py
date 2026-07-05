import unittest
from unittest.mock import patch

from dodo_parser.dodo import CityMenuResult, PizzeriaResult
from dodo_parser.report import build_report, resolve_pizza_name


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

    def test_build_report_shows_only_first_five_pizzerias(self) -> None:
        config = {
            "pizza_name": "Пепперони",
            "check_city_menu": False,
            "check_pizzerias": True,
            "pizzeria_preview_limit": 5,
        }
        fake_results = [
            PizzeriaResult(
                pizzeria_name=f"Точка {index}",
                pizzeria_id=str(index),
                found=True,
                matches=["Пепперони"],
                url=f"https://example.com/{index}",
            )
            for index in range(1, 8)
        ]

        with patch("dodo_parser.report.create_dodo_client", return_value=FakeDodoClient(fake_results)):
            report = build_report(config)

        self.assertIn("Кафе, где сейчас есть 'Пепперони': 7", report)
        self.assertIn("Точка 1", report)
        self.assertIn("Точка 5", report)
        self.assertNotIn("Точка 6", report)
        self.assertNotIn("Точка 7", report)
        self.assertIn("Показываю первые 5 точек из 7.", report)


class FakeDodoClient:
    def check_city_menu(self, pizza_name: str) -> CityMenuResult:
        return CityMenuResult(found=False, matches=[])

    def check_pizzerias(self, pizza_name: str) -> list[PizzeriaResult]:
        return [
            PizzeriaResult(
                pizzeria_name=result.pizzeria_name,
                pizzeria_id=result.pizzeria_id,
                found=result.found,
                matches=result.matches,
                url=result.url,
            )
            for result in self._results
        ]

    def __init__(self, results: list[PizzeriaResult]) -> None:
        self._results = results


if __name__ == "__main__":
    unittest.main()
