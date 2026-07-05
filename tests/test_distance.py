import unittest

from dodo_parser.distance import DistanceMatrixClient, RouteDistance


class DistanceMatrixClientTests(unittest.TestCase):
    def test_get_distances_batches_requests(self) -> None:
        client = FakeDistanceMatrixClient(batch_size=2)

        result = client.get_distances(
            origin_latitude=55.75,
            origin_longitude=37.61,
            destinations=[(55.76, 37.62), (55.77, 37.63), (55.78, 37.64)],
        )

        self.assertEqual(
            result,
            [
                RouteDistance(distance_meters=1000.0, duration_seconds=300.0),
                RouteDistance(distance_meters=2000.0, duration_seconds=600.0),
                RouteDistance(distance_meters=1000.0, duration_seconds=300.0),
            ],
        )
        self.assertEqual(client.request_sizes, [2, 1])


class FakeDistanceMatrixClient(DistanceMatrixClient):
    def __init__(self, *, batch_size: int) -> None:
        super().__init__(base_url="https://example.test", profile="driving", batch_size=batch_size)
        self.request_sizes: list[int] = []

    def _request_table(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destinations: list[tuple[float, float]],
    ) -> list[RouteDistance | None]:
        self.request_sizes.append(len(destinations))
        return [
            RouteDistance(distance_meters=1000.0 * (index + 1), duration_seconds=300.0 * (index + 1))
            for index, _ in enumerate(destinations)
        ]


if __name__ == "__main__":
    unittest.main()
