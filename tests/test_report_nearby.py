import unittest
from unittest.mock import patch

from dodo_parser.dodo import PizzeriaResult
from dodo_parser.distance import RouteDistance
from dodo_parser.report import build_nearby_report


class NearbyReportTests(unittest.TestCase):
    def test_build_nearby_report_sorts_and_limits_results(self) -> None:
        config = {
            "pizza_name": "Пепперони",
            "nearby_results_limit": 2,
            "distance_api_url": "https://router.project-osrm.org",
        }
        fake_results = [
            PizzeriaResult(
                pizzeria_name="Точка 1",
                pizzeria_id="1",
                found=True,
                matches=["Пепперони"],
                url="https://example.com/1",
                address="Адрес 1",
                latitude=55.70,
                longitude=37.70,
            ),
            PizzeriaResult(
                pizzeria_name="Точка 2",
                pizzeria_id="2",
                found=True,
                matches=["Пепперони"],
                url="https://example.com/2",
                address="Адрес 2",
                latitude=55.71,
                longitude=37.71,
            ),
            PizzeriaResult(
                pizzeria_name="Точка 3",
                pizzeria_id="3",
                found=True,
                matches=["Пепперони"],
                url="https://example.com/3",
                address="Адрес 3",
                latitude=55.72,
                longitude=37.72,
            ),
        ]

        with patch("dodo_parser.report.create_dodo_client", return_value=FakeDodoClient(fake_results)):
            with patch("dodo_parser.report.DistanceMatrixClient", return_value=FakeDistanceClient()):
                report = build_nearby_report(config, latitude=55.75, longitude=37.61)

        self.assertIn("1. Точка 2", report)
        self.assertIn("2. Точка 1", report)
        self.assertNotIn("3. Точка 3", report)
        self.assertIn("Показываю первые 2 из 3", report)

    def test_build_nearby_report_handles_missing_available_points(self) -> None:
        config = {"pizza_name": "Пепперони"}
        fake_results = [
            PizzeriaResult(
                pizzeria_name="Точка 1",
                pizzeria_id="1",
                found=False,
                matches=[],
            )
        ]

        with patch("dodo_parser.report.create_dodo_client", return_value=FakeDodoClient(fake_results)):
            report = build_nearby_report(config, latitude=55.75, longitude=37.61)

        self.assertIn("Не нашёл ни одной открытой пиццерии", report)


class FakeDodoClient:
    def __init__(self, results: list[PizzeriaResult]) -> None:
        self.results = results

    def check_pizzerias(self, pizza_name: str) -> list[PizzeriaResult]:
        return self.results


class FakeDistanceClient:
    def get_distances(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destinations: list[tuple[float, float]],
    ) -> list[RouteDistance | None]:
        lookup = {
            (55.70, 37.70): RouteDistance(distance_meters=1800.0, duration_seconds=420.0),
            (55.71, 37.71): RouteDistance(distance_meters=1200.0, duration_seconds=360.0),
            (55.72, 37.72): RouteDistance(distance_meters=2500.0, duration_seconds=540.0),
        }
        return [lookup[item] for item in destinations]


if __name__ == "__main__":
    unittest.main()
