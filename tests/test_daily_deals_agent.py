import unittest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

from agent.daily_deals_agent import (
    Offer,
    detect_sales,
    discover_offers,
    ensure_history_table,
    parse_json_ld_offers,
    parse_serpapi_shopping_results,
    parse_shipping_cost,
    log_http_exchange,
    write_last_response,
)


class DailyDealsAgentTests(unittest.TestCase):
    def test_write_last_response_overwrites_json_file(self):
        with TemporaryDirectory() as temp_dir:
            response_path = Path(temp_dir) / "data" / "last_response.json"
            write_last_response(response_path, {"query": "iphone", "price": 999})
            write_last_response(response_path, {"query": "pixel", "price": 799})

            self.assertEqual(
                json.loads(response_path.read_text(encoding="utf-8")),
                {"query": "pixel", "price": 799},
            )

    def test_verbose_logging_redacts_api_key(self):
        response = unittest.mock.MagicMock()
        response.request.url = "https://serpapi.com/search.json?api_key=secret-key&q=iphone"
        response.url = response.request.url
        response.status_code = 200
        response.headers = {"content-type": "application/json"}
        response.text = '{"shopping_results": []}'

        with patch("agent.daily_deals_agent.VERBOSE_LOGGING", True), self.assertLogs(
            "agent.daily_deals_agent", level="DEBUG"
        ) as logs:
            log_http_exchange("SerpAPI", response)

        output = "\n".join(logs.output)
        self.assertIn("api_key=<redacted>", output)
        self.assertNotIn("secret-key", output)

    def test_parse_serpapi_shopping_results_extracts_mock_prices(self):
        mock_path = Path(__file__).parents[1] / "mock_results.json"
        with mock_path.open("r", encoding="utf-8") as file:
            search_data = json.load(file)

        offers = parse_serpapi_shopping_results(
            item="40mm to 50mm Studded Winter Bike Tires",
            search_data=search_data,
        )

        self.assertEqual(len(offers), len(search_data["shopping_results"]))
        self.assertEqual(offers[0].price, 61.30)
        self.assertEqual(offers[1].price, 225.00)
        self.assertEqual(offers[0].retailer, "Ebikecan")

    @patch("agent.daily_deals_agent.requests.get")
    def test_discover_offers_keeps_results_that_do_not_ship_to_canada(self, get):
        mock_path = Path(__file__).parents[1] / "mock_results.json"
        with mock_path.open("r", encoding="utf-8") as file:
            search_data = json.load(file)

        response = unittest.mock.MagicMock()
        response.json.return_value = search_data
        response.status_code = 200
        response.headers = {}
        response.text = json.dumps(search_data)
        response.request.url = "https://serpapi.com/search.json"
        get.return_value = response

        with (
            patch("agent.daily_deals_agent.SERPAPI_API_KEY", "test-key"),
            patch("agent.daily_deals_agent.LAST_RESPONSE_FILE", Path("last_response_test.json")),
        ):
            offers = discover_offers("winter bike tires")

        self.assertEqual(len(offers), len(search_data["shopping_results"]))
        self.assertTrue(any(not offer.ships_to_canada for offer in offers))

    @unittest.skipUnless(os.getenv("SERPAPI_API_KEY"), "SERPAPI_API_KEY is not configured")
    def test_serpapi_external_api_is_reachable(self):
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "api_key": os.environ["SERPAPI_API_KEY"],
                "engine": "google_shopping",
                "q": "winter bike tire",
                "num": 1,
            },
            timeout=15,
        )
        response.raise_for_status()
        search_data = response.json()

        self.assertNotIn("error", search_data)
        self.assertIsInstance(search_data.get("shopping_results"), list)

    @unittest.skipUnless(os.getenv("SERPAPI_API_KEY"), "SERPAPI_API_KEY is not configured")
    def test_serpapi_iphone_search_returns_priced_products(self):
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "api_key": os.environ["SERPAPI_API_KEY"],
                "engine": "google_shopping",
                "q": "iphone",
                "num": 5,
            },
            timeout=15,
        )
        response.raise_for_status()
        search_data = response.json()

        offers = parse_serpapi_shopping_results(item="iphone", search_data=search_data)
        titles = [str(result.get("title", "")).lower() for result in search_data["shopping_results"]]

        self.assertTrue(search_data["shopping_results"])
        self.assertTrue(any("iphone" in title for title in titles))
        self.assertTrue(offers)
        self.assertTrue(all(offer.price > 0 for offer in offers))

    def test_parse_shipping_cost_detects_free_shipping(self):
        self.assertEqual(parse_shipping_cost("Fast delivery with FREE shipping to Canada"), 0.0)

    def test_parse_jsonld_offer_extracts_price_and_shipping(self):
        html = """
        <html><head>
        <script type=\"application/ld+json\">
        {"@type":"Product","offers":{"@type":"Offer","price":"299.99","priceCurrency":"CAD","shippingDetails":{"shippingRate":{"value":"14.99"}}}}
        </script>
        </head><body>Ships to Canada</body></html>
        """
        offers = parse_json_ld_offers(item="Steam Deck", url="https://example.ca/p/1", html=html)

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 299.99)
        self.assertEqual(offers[0].shipping_cost, 14.99)
        self.assertTrue(offers[0].ships_to_canada)

    def test_detect_sales_only_when_price_drops(self):
        current = [
            Offer("Keyboard", "shop.ca", "https://shop.ca/k", 79.99, "CAD", 9.99, True),
            Offer("Mouse", "shop.ca", "https://shop.ca/m", 39.99, "CAD", 4.99, True),
        ]
        previous = {
            ("Keyboard", "shop.ca", "https://shop.ca/k"): 89.99,
            ("Mouse", "shop.ca", "https://shop.ca/m"): 35.00,
        }

        alerts = detect_sales(current=current, previous_prices=previous)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].item, "Keyboard")

    @patch("agent.daily_deals_agent.requests.get")
    def test_discover_offers_handles_serpapi_errors(self, get):
        get.side_effect = RuntimeError("rate limited")

        with patch("agent.daily_deals_agent.SERPAPI_API_KEY", "test-key"):
            offers = discover_offers("Winter Bike Tires")

        self.assertEqual(offers, [])

    def test_ensure_history_table_creates_schema(self):
        connection = unittest.mock.MagicMock()

        ensure_history_table(connection)

        connection.cursor.assert_called_once_with()
        connection.commit.assert_called_once_with()
        cursor = connection.cursor.return_value.__enter__.return_value
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn("CREATE TABLE IF NOT EXISTS price_history", cursor.execute.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
