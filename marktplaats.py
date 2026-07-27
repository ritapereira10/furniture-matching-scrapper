"""
Shared Marktplaats scraping utilities.

Extracted from main.py so the same scraping/matching logic can be reused
by both the FastAPI app and the standalone weekly_digest.py job, without
duplicating the scraping code.
"""

import re
import logging
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.marktplaats.nl"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
}

# CSS selectors centralised so it’s easy to tweak if MP changes DOM
SEL = {
    "card": "li.mp-Listing",
    "title": "[data-testid='listing-title']",
    "price": "[data-testid='ad-price']",
    "location": "[data-testid='location']",
    "date": "[data-testid='date']",
    "link": "a[href]",
    "image": "img",
    "desc": "[data-testid='description']",
}

CITY_POSTCODES = {
    "amsterdam": "1012AB",
    "rotterdam": "3011AD",
    "den-haag": "2511AA",
    "utrecht": "3511AA",
    "eindhoven": "5611AA",
    "groningen": "9711AA",
    "tilburg": "5011AA",
    "almere": "1311AA"
}

CITY_REGIONS = {
    "amsterdam": ["amsterdam", "amstelveen", "diemen", "ouderkerk", "duivendrecht", "zaandam", "weesp", "abcoude", "uithoorn", "aalsmeer", "hoofddorp", "badhoevedorp", "schiphol"],
    "rotterdam": ["rotterdam", "schiedam", "vlaardingen", "capelle", "ridderkerk", "barendrecht", "spijkenisse", "hoogvliet", "pernis", "delfshaven"],
    "den-haag": ["den haag", "'s-gravenhage", "rijswijk", "voorburg", "leidschendam", "wassenaar", "delft", "zoetermeer", "loosduinen"],
    "utrecht": ["utrecht", "nieuwegein", "ijsselstein", "houten", "zeist", "de bilt", "bunnik", "maarssen", "bilthoven"],
    "eindhoven": ["eindhoven", "veldhoven", "geldrop", "nuenen", "best", "son", "waalre", "valkenswaard"],
    "groningen": ["groningen", "haren", "hoogezand", "zuidhorn", "leek", "roden"],
    "tilburg": ["tilburg", "goirle", "oisterwijk", "gilze", "rijen", "dongen", "waalwijk"],
    "almere": ["almere", "lelystad", "huizen", "naarden", "bussum", "hilversum", "muiden"]
}


def parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = text.strip().lower()
    if any(x in t for x in ["bieden", "gratis", "n.o.t.k", "prijs op aanvraag"]):
        return None
    m = re.findall(r"[\d\.\,]+", t)
    if not m:
        return None
    try:
        return float(m[0].replace(".", "").replace(",", "."))
    except:
        return None


def extract_id(url: str) -> str:
    # Common MP patterns like -m123456789 or /v/123456789
    m = re.search(r"-(m?\d+)(?:\.|$|/)", url)
    if m:
        return m.group(1)
    m = re.search(r"/v/(\d+)", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-24:]


def is_location_in_city_region(location: str, city: str) -> bool:
    """Check if a location string matches the city or nearby areas within ~20km."""
    if not location:
        return True

    location_lower = location.lower().strip()
    city_lower = city.lower()

    if city_lower in location_lower:
        return True

    allowed_areas = CITY_REGIONS.get(city_lower, [city_lower])
    for area in allowed_areas:
        if area in location_lower:
            return True

    return False


def search_marktplaats_listings(queries: list, city: str = "amsterdam", max_per_query: int = 8) -> list:
    """Search Marktplaats and return raw listing data within 20km of city."""
    postcode = CITY_POSTCODES.get(city, "1012AB")
    all_listings = []
    seen_ids = set()

    for query in queries[:6]:
        try:
            search_url = f"{BASE}/z.html"
            params = {
                "query": query,
                "postcode": postcode,
                "distanceMeters": 20000
            }
            logger.info(f"Searching {city} ({postcode}): {query}")

            resp = requests.get(search_url, params=params, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.content, "lxml")

            listings = soup.select(SEL["card"])[:max_per_query]

            if len(listings) == 0:
                alt_selectors = ["li[data-testid='listing-item']", "article[data-testid='listing']", ".hz-Listing"]
                for alt_sel in alt_selectors:
                    listings = soup.select(alt_sel)
                    if len(listings) > 0:
                        break

            for listing in listings:
                title_el = listing.select_one(SEL["title"]) or listing.select_one("h3")
                price_el = listing.select_one(SEL["price"])
                img_el = listing.select_one(SEL["image"])
                link_el = listing.select_one(SEL["link"])
                loc_el = listing.select_one(SEL["location"])
                desc_el = listing.select_one(SEL["desc"])

                if not title_el or not link_el:
                    continue

                href = link_el.get("href", "")
                listing_id = re.search(r'/a(\d+)', href)
                lid = listing_id.group(1) if listing_id else href

                if lid in seen_ids:
                    continue
                seen_ids.add(lid)

                title = title_el.get_text(strip=True)
                price_text = price_el.get_text(strip=True) if price_el else "Prijs op aanvraag"
                image_url = img_el.get("src") if img_el and img_el.has_attr("src") else None
                listing_url = urljoin(BASE, href)
                location = loc_el.get_text(strip=True) if loc_el else city.capitalize()
                description = desc_el.get_text(strip=True)[:200] if desc_el else ""

                if not is_location_in_city_region(location, city):
                    logger.debug(f"Filtered out item outside region: {location} (searching {city})")
                    continue

                all_listings.append({
                    "id": lid,
                    "title": title,
                    "price": price_text,
                    "image": image_url,
                    "url": listing_url,
                    "location": location,
                    "description": description
                })

        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            continue

    logger.info(f"After location filtering: {len(all_listings)} listings in {city} region")
    return all_listings
