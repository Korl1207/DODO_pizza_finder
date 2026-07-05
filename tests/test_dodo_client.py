import unittest

from dodo_parser.dodo import DodoClient, DodoHTTPError


class FakePage:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict] = []

    def evaluate(self, _script: str, args: dict) -> dict:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.payload


class DodoClientPageRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = DodoClient(
            city="moscow",
            country_code="RU",
            country_id=643,
            culture="ru-RU",
            locality_id="0000002b-0000-0000-0000-000000000000",
            api_version="v5",
            menu_type="delivery",
        )

    def test_request_json_with_page_parses_successful_json(self) -> None:
        page = FakePage(payload={"ok": True, "status": 200, "text": '[{"id": 1}]'})

        data = self.client._request_json_with_page(page, "https://dodopizza.ru/api/pizzerias")

        self.assertEqual(data, [{"id": 1}])
        self.assertEqual(page.calls[0]["countryCode"], "RU")
        self.assertEqual(page.calls[0]["culture"], "ru-RU")

    def test_request_json_with_page_raises_on_http_error(self) -> None:
        page = FakePage(payload={"ok": False, "status": 504, "text": ""})

        with self.assertRaises(DodoHTTPError) as ctx:
            self.client._request_json_with_page(page, "https://dodopizza.ru/api/pizzerias")

        self.assertIn("HTTP 504", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
