#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List

import psycopg
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

PROMPTS_FILE = Path(os.getenv("PROMPTS_FILE", "shopping_prompts.txt"))
DATABASE_URL = os.getenv("DATABASE_URL")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "false").lower() in {"1", "true", "yes", "on"}
SALE_REPORT_FILE = Path(os.getenv("SALE_REPORT_FILE", "data/sale_report.txt"))
LAST_RESPONSE_FILE = Path(os.getenv("LAST_RESPONSE_FILE", "data/last_response.json"))
MAX_RESULTS_PER_ITEM = int(os.getenv("MAX_RESULTS_PER_ITEM", "20"))
TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

PRICE_HISTORY_TABLE = "price_history"
SERPAPI_URL = "https://serpapi.com/search.json"

if VERBOSE_LOGGING:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@dataclass
class Offer:
    item: str
    retailer: str
    url: str
    price: float
    currency: str
    shipping_cost: float
    ships_to_canada: bool


@dataclass
class SaleAlert:
    item: str
    retailer: str
    url: str
    old_price: float
    new_price: float
    shipping_cost: float


def log_http_exchange(label: str, response: requests.Response) -> None:
    if not VERBOSE_LOGGING:
        return

    request_url = response.request.url if response.request else response.url
    safe_url = re.sub(r"([?&]api_key=)[^&]+", r"\1<redacted>", request_url)
    LOGGER.debug("%s request URL: %s", label, safe_url)
    LOGGER.debug(
        "%s response: status=%s headers=%s body=%s",
        label,
        response.status_code,
        dict(response.headers),
        response.text,
    )


def write_last_response(path: Path, response_data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response_data, indent=2) + "\n", encoding="utf-8")


def load_item_prompts(path: Path) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]


def extract_domain(url: str) -> str:
    domain = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    return domain.split("/")[0].lower().replace("www.", "")


def parse_money(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d{1,2})?)", text)
    if not m:
        return None
    return float(m.group(1))


def parse_shipping_cost(raw_text: str) -> float:
    lowered = raw_text.lower()
    if "free shipping" in lowered or "free delivery" in lowered:
        return 0.0
    m = re.search(r"(?:shipping|delivery)[^$\d]*(?:\$|cad\s*)(\d+(?:\.\d{1,2})?)", lowered)
    if m:
        return float(m.group(1))
    return 0.0


def parse_json_ld_offers(item: str, url: str, html: str) -> List[Offer]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    ships_to_canada = "canada" in page_text.lower() or ".ca" in extract_domain(url)

    offers: list[Offer] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        nodes: Iterable[dict] = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                nodes = [node for node in data["@graph"] if isinstance(node, dict)]
            else:
                nodes = [data]
        elif isinstance(data, list):
            nodes = [node for node in data if isinstance(node, dict)]

        for node in nodes:
            node_type = str(node.get("@type", "")).lower()
            if "product" not in node_type and "offer" not in node_type:
                continue
            offer_data = node.get("offers", node)
            offer_list = offer_data if isinstance(offer_data, list) else [offer_data]
            for offer_node in offer_list:
                if not isinstance(offer_node, dict):
                    continue

                price = parse_money(offer_node.get("price") or offer_node.get("priceSpecification"))
                if price is None:
                    continue

                currency = str(offer_node.get("priceCurrency") or "CAD").upper()
                shipping_cost = parse_shipping_cost(page_text)

                shipping_details = offer_node.get("shippingDetails")
                if isinstance(shipping_details, dict):
                    shipping_rate = shipping_details.get("shippingRate")
                    if isinstance(shipping_rate, dict):
                        shipping_cost = parse_money(shipping_rate.get("value")) or shipping_cost
                    destinations = json.dumps(shipping_details).lower()
                    ships_to_canada = ships_to_canada or ("canada" in destinations or "ca" in destinations)

                offers.append(
                    Offer(
                        item=item,
                        retailer=extract_domain(url),
                        url=url,
                        price=price,
                        currency=currency,
                        shipping_cost=shipping_cost,
                        ships_to_canada=ships_to_canada,
                    )
                )

    return offers


def parse_serpapi_shopping_results(item: str, search_data: dict) -> List[Offer]:
    offers: list[Offer] = []
    for result in search_data.get("shopping_results", []):
        if not isinstance(result, dict):
            continue

        price = parse_money(result.get("extracted_price") or result.get("price"))
        url = result.get("link") or result.get("product_link")
        if price is None or not url:
            continue

        delivery = str(result.get("delivery") or "")
        offers.append(
            Offer(
                item=item,
                retailer=str(result.get("source") or extract_domain(url)),
                url=url,
                price=price,
                currency="CAD",
                shipping_cost=parse_shipping_cost(delivery),
                ships_to_canada="canada" in delivery.lower() or ".ca" in extract_domain(url),
            )
        )

    return offers


def discover_offers(item: str) -> List[Offer]:
    if not SERPAPI_API_KEY:
        raise RuntimeError("SERPAPI_API_KEY must be configured")

    query = f"{item} Canada"
    urls: list[str] = []

    try:
        response = requests.get(
            SERPAPI_URL,
            params={
                "api_key": SERPAPI_API_KEY,
                "engine": "google_shopping",
                "q": query,
                "num": MAX_RESULTS_PER_ITEM,
            },
            timeout=TIMEOUT_SECONDS,
        )
        log_http_exchange("SerpAPI", response)
        response.raise_for_status()
        search_data = response.json()
        write_last_response(LAST_RESPONSE_FILE, search_data)
        if search_data.get("error"):
            raise RuntimeError(search_data["error"])
        shopping_offers = parse_serpapi_shopping_results(item=item, search_data=search_data)
        if shopping_offers:
            return shopping_offers
        for result in search_data.get("organic_results", []):
            href = result.get("link")
            if href and href.startswith("http"):
                urls.append(href)
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        print(f"SerpAPI search failed for '{item}': {exc}")
        return []

    offers: list[Offer] = []
    for url in urls:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "ShoppingBotDealsAgent/1.0"},
                timeout=TIMEOUT_SECONDS,
            )
            log_http_exchange("Retailer", response)
            response.raise_for_status()
            offers.extend(parse_json_ld_offers(item=item, url=url, html=response.text))
        except requests.RequestException:
            continue

    unique: dict[tuple[str, str], Offer] = {}
    for offer in offers:
        key = (offer.url, offer.retailer)
        if key not in unique or offer.price < unique[key].price:
            unique[key] = offer

    return list(unique.values())


def get_database_connection() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be configured")
    return psycopg.connect(DATABASE_URL)


def ensure_history_table(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PRICE_HISTORY_TABLE} (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                timestamp_utc TIMESTAMPTZ NOT NULL,
                item TEXT NOT NULL,
                retailer TEXT NOT NULL,
                url TEXT NOT NULL,
                price NUMERIC(12, 2) NOT NULL,
                currency TEXT NOT NULL,
                shipping_cost NUMERIC(12, 2) NOT NULL,
                ships_to_canada BOOLEAN NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS price_history_lookup_idx
            ON {PRICE_HISTORY_TABLE} (item, retailer, url, timestamp_utc DESC)
            """
        )
    connection.commit()


def append_history(connection: psycopg.Connection, offers: list[Offer], timestamp_utc: str) -> None:
    if not offers:
        return
    with connection.cursor() as cursor:
        cursor.executemany(
            f"""
            INSERT INTO {PRICE_HISTORY_TABLE}
                (timestamp_utc, item, retailer, url, price, currency, shipping_cost, ships_to_canada)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    timestamp_utc,
                    offer.item,
                    offer.retailer,
                    offer.url,
                    offer.price,
                    offer.currency,
                    offer.shipping_cost,
                    offer.ships_to_canada,
                )
                for offer in offers
            ],
        )
    connection.commit()


def load_previous_prices(connection: psycopg.Connection) -> dict[tuple[str, str, str], float]:
    previous: dict[tuple[str, str, str], float] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT ON (item, retailer, url) item, retailer, url, price
            FROM {PRICE_HISTORY_TABLE}
            ORDER BY item, retailer, url, timestamp_utc DESC, id DESC
            """
        )
        for item, retailer, url, price in cursor.fetchall():
            previous[(item, retailer, url)] = float(price)
    return previous


def detect_sales(current: list[Offer], previous_prices: dict[tuple[str, str, str], float]) -> list[SaleAlert]:
    alerts: list[SaleAlert] = []
    for offer in current:
        key = (offer.item, offer.retailer, offer.url)
        previous = previous_prices.get(key)
        if previous is None:
            continue
        if offer.price < previous:
            alerts.append(
                SaleAlert(
                    item=offer.item,
                    retailer=offer.retailer,
                    url=offer.url,
                    old_price=previous,
                    new_price=offer.price,
                    shipping_cost=offer.shipping_cost,
                )
            )
    return alerts


def build_email_body(alerts: list[SaleAlert]) -> str:
    lines = ["ShoppingBot detected new sale prices:", ""]
    for alert in alerts:
        lines.extend(
            [
                f"- {alert.item}",
                f"  Retailer: {alert.retailer}",
                f"  Old price: ${alert.old_price:.2f}",
                f"  New price: ${alert.new_price:.2f}",
                f"  Shipping: ${alert.shipping_cost:.2f}",
                f"  Link: {alert.url}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def send_email_if_configured(body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    to_email = os.getenv("ALERT_EMAIL_TO")
    from_email = os.getenv("ALERT_EMAIL_FROM") or username

    if not all([host, port, username, password, to_email, from_email]):
        return

    msg = EmailMessage()
    msg["Subject"] = "ShoppingBot Sale Alert"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(host, int(port)) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)


def write_sale_report(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def ensure_runtime_files(connection: psycopg.Connection) -> None:
    ensure_history_table(connection)
    SALE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SALE_REPORT_FILE.exists():
        SALE_REPORT_FILE.touch()


def main() -> int:
    with get_database_connection() as connection:
        ensure_runtime_files(connection)
        items = load_item_prompts(PROMPTS_FILE)
        if not items:
            print(f"No items found in {PROMPTS_FILE}")
            return 0

        previous_prices = load_previous_prices(connection)
        all_offers: list[Offer] = []

        for item in items:
            all_offers.extend(discover_offers(item))

        now = datetime.now(timezone.utc).isoformat()
        append_history(connection, all_offers, now)

        alerts = detect_sales(current=all_offers, previous_prices=previous_prices)
        if not alerts:
            print("No sales detected")
            return 0

        body = build_email_body(alerts)
        write_sale_report(SALE_REPORT_FILE, body)
        send_email_if_configured(body)
        print(f"Detected {len(alerts)} sale alerts")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
