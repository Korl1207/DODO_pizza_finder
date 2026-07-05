from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_DISTANCE_API_URL = "https://router.project-osrm.org"
DEFAULT_DISTANCE_PROFILE = "driving"
DEFAULT_BATCH_SIZE = 25


@dataclass(frozen=True)
class RouteDistance:
    distance_meters: float
    duration_seconds: float


class DistanceAPIError(RuntimeError):
    """Raised when the routing provider cannot return distances."""


class DistanceMatrixClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_DISTANCE_API_URL,
        profile: str = DEFAULT_DISTANCE_PROFILE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile.strip() or DEFAULT_DISTANCE_PROFILE
        self.batch_size = max(1, int(batch_size))

    def get_distances(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destinations: list[tuple[float, float]],
    ) -> list[RouteDistance | None]:
        results: list[RouteDistance | None] = []
        for index in range(0, len(destinations), self.batch_size):
            chunk = destinations[index : index + self.batch_size]
            results.extend(
                self._request_table(
                    origin_latitude=origin_latitude,
                    origin_longitude=origin_longitude,
                    destinations=chunk,
                )
            )
        return results

    def _request_table(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destinations: list[tuple[float, float]],
    ) -> list[RouteDistance | None]:
        coordinates = [self._format_coordinate(origin_latitude, origin_longitude)]
        coordinates.extend(self._format_coordinate(latitude, longitude) for latitude, longitude in destinations)
        query = urlencode(
            {
                "sources": "0",
                "destinations": ";".join(str(item) for item in range(1, len(coordinates))),
                "annotations": "distance,duration",
            }
        )
        url = f"{self.base_url}/table/v1/{self.profile}/{';'.join(coordinates)}?{query}"
        payload = self._get_json(url)
        if payload.get("code") != "Ok":
            raise DistanceAPIError(f"Routing API returned an error: {payload.get('code') or 'unknown'}")

        distances = payload.get("distances")
        durations = payload.get("durations")
        if not isinstance(distances, list) or not distances or not isinstance(distances[0], list):
            raise DistanceAPIError("Routing API returned an unexpected distances payload")
        if not isinstance(durations, list) or not durations or not isinstance(durations[0], list):
            raise DistanceAPIError("Routing API returned an unexpected durations payload")

        results: list[RouteDistance | None] = []
        for distance_value, duration_value in zip(distances[0], durations[0]):
            if distance_value is None or duration_value is None:
                results.append(None)
                continue
            results.append(
                RouteDistance(
                    distance_meters=float(distance_value),
                    duration_seconds=float(duration_value),
                )
            )
        return results

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise DistanceAPIError(f"Routing API returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise DistanceAPIError(f"Routing API request failed: {exc.reason}") from exc

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DistanceAPIError("Routing API did not return JSON") from exc
        if not isinstance(data, dict):
            raise DistanceAPIError("Routing API returned an unexpected payload")
        return data

    @staticmethod
    def _format_coordinate(latitude: float, longitude: float) -> str:
        return f"{float(longitude):.6f},{float(latitude):.6f}"
