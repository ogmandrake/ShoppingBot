import unittest
from unittest.mock import patch

from agent.daily_deals_agent import (
    Offer,
    detect_sales,
    discover_offers,
    ensure_history_table,
    parse_json_ld_offers,
    parse_shipping_cost,
)


class DailyDealsAgentTests(unittest.TestCase):
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
