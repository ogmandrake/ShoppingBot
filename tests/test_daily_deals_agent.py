import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import RatelimitException

from agent.daily_deals_agent import (
    Offer,
    detect_sales,
    discover_offers,
    ensure_runtime_files,
    parse_json_ld_offers,
    parse_shipping_cost,
)


class DailyDealsAgentTests(unittest.TestCase):
    def test_ddgs_client_initializes(self):
        with DDGS() as ddgs:
            self.assertIsNotNone(ddgs)

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

    @patch("agent.daily_deals_agent.DDGS")
    def test_discover_offers_handles_ddgs_rate_limits(self, ddgs_cls):
        ddgs = ddgs_cls.return_value.__enter__.return_value
        ddgs.text.side_effect = RatelimitException("rate limited")

        offers = discover_offers("Winter Bike Tires")

        self.assertEqual(offers, [])

    def test_ensure_runtime_files_creates_history_and_sale_report(self):
        with TemporaryDirectory() as tmp_dir:
            history_file = Path(tmp_dir) / "data" / "price_history.csv"
            sale_report_file = Path(tmp_dir) / "data" / "sale_report.txt"
            with (
                patch("agent.daily_deals_agent.HISTORY_FILE", history_file),
                patch("agent.daily_deals_agent.SALE_REPORT_FILE", sale_report_file),
            ):
                ensure_runtime_files()

            self.assertTrue(history_file.exists())
            self.assertTrue(sale_report_file.exists())


if __name__ == "__main__":
    unittest.main()
