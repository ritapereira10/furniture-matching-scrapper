from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from pydantic import BaseModel
import uvicorn
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from typing import Optional, List
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Templates
templates = Jinja2Templates(directory="templates")

app = FastAPI(
    title="Marktplaats Scraper API", 
    description="""
    ## Marktplaats Scraper API for Pinterest Board Matching
    
    This API scrapes Marktplaats listings to help match items from Pinterest boards with available marketplace items.
    
    ### Main Endpoints:
    - **GET /scrape**: Single search query with pagination
    - **POST /batch-search**: Multiple search queries for Pinterest board matching
    - **GET /health**: Health check endpoint
    
    ### Usage for Pinterest Integration:
    1. Extract item descriptions from Pinterest board
    2. Use `/batch-search` with list of search terms
    3. Get structured Marktplaats listings with titles, prices, locations, and links
    
    ### Data Returned:
    - **title**: Item title from Marktplaats
    - **price_eur**: Numeric price in euros (if available)
    - **price_text**: Raw price text (includes "Bieden" for negotiable items)
    - **location**: Item location/seller area
    - **url**: Direct link to Marktplaats listing
    - **image_url**: Product image URL
    - **description**: Item description (when available)
    """,
    version="1.0.0"
)

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

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/scrape")
def scrape(
    query: str = Query("dressoir", description="Search term"),
    pages: int = Query(1, ge=1, le=5, description="How many result pages to fetch"),
):
    try:
        seen = set()
        items: List[dict] = []

        for p in range(1, pages + 1):
            url = f"{BASE}/q/{query}/?p={p}"
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select(SEL["card"])
            logger.info(f"Found {len(cards)} cards on page {p} for query '{query}'")
            
            if len(cards) == 0:
                # Try alternative selectors if the main one doesn't work
                alt_selectors = ["li[data-testid='listing-item']", "article[data-testid='listing']", ".hz-Listing", ".mp-listing-item", "li.mp-Listing-item"]
                for alt_sel in alt_selectors:
                    cards = soup.select(alt_sel)
                    if len(cards) > 0:
                        logger.info(f"Using alternative selector '{alt_sel}' - found {len(cards)} cards")
                        break
                        
            # Debug: log first card HTML structure to understand the format
            if len(cards) > 0 and p == 1:
                logger.info(f"First card HTML preview: {str(cards[0])[:500]}...")
            
            for c in cards:
                a = c.select_one(SEL["link"])
                if not a:
                    continue
                href = a.get("href", "")
                if not href or not isinstance(href, str):
                    continue
                full_url = href if href.startswith("http") else urljoin(BASE, href)
                lid = extract_id(full_url)
                if lid in seen:
                    continue
                seen.add(lid)

                # Try multiple selectors for each field
                title_el = c.select_one(SEL["title"]) or c.select_one("h3") or c.select_one(".hz-Listing-title")
                price_el = c.select_one(SEL["price"]) or c.select_one(".hz-Listing-price") or c.select_one("[data-testid*='price']")
                loc_el = c.select_one(SEL["location"]) or c.select_one(".hz-Listing-location") or c.select_one("[data-testid*='location']")
                date_el = c.select_one(SEL["date"]) or c.select_one(".hz-Listing-date") or c.select_one("[data-testid*='date']")
                img_el = c.select_one(SEL["image"]) or c.select_one("img")
                desc_el = c.select_one(SEL["desc"]) or c.select_one(".hz-Listing-description") or c.select_one("[data-testid*='desc']")

                item = {
                    "id": lid,
                    "url": full_url,
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "price_text": price_el.get_text(strip=True) if price_el else None,
                    "price_eur": parse_price(price_el.get_text(strip=True)) if price_el else None,
                    "location": loc_el.get_text(strip=True) if loc_el else None,
                    "posted_at": date_el.get_text(strip=True) if date_el else None,
                    "image_url": img_el.get("src") if img_el and img_el.has_attr("src") else None,
                    "description": desc_el.get_text(strip=True) if desc_el else None,
                }
                items.append(item)

        # Sort: show priced items first, lowest price first
        items.sort(key=lambda x: (x["price_eur"] is None, x["price_eur"] if x["price_eur"] is not None else 1e12))

        return {"query": query, "pages": pages, "count": len(items), "items": items}

    except Exception as e:
        return {"error": "An error occurred while scraping", "details": str(e)}

class BatchSearchRequest(BaseModel):
    queries: List[str]
    max_results_per_query: Optional[int] = 20
    pages_per_query: Optional[int] = 1

@app.post("/batch-search")
def batch_search(request: BatchSearchRequest):
    """
    Batch search multiple queries at once (useful for Pinterest board matching)
    
    - **queries**: List of search terms (e.g., ["vintage chair", "ceramic vase", "antique lamp"])
    - **max_results_per_query**: Maximum results per query (default: 20)
    - **pages_per_query**: Pages to search per query (default: 1)
    """
    try:
        results = {}
        total_items = 0
        
        for query in request.queries:
            logger.info(f"Batch searching for: {query}")
            
            # Use the existing scrape function logic
            seen = set()
            items: List[dict] = []

            for p in range(1, (request.pages_per_query or 1) + 1):
                url = f"{BASE}/q/{query}/?p={p}"
                r = requests.get(url, headers=HEADERS, timeout=20)
                r.raise_for_status()

                soup = BeautifulSoup(r.text, "lxml")
                cards = soup.select(SEL["card"])
                
                if len(cards) == 0:
                    # Try alternative selectors
                    alt_selectors = ["li[data-testid='listing-item']", "article[data-testid='listing']", ".hz-Listing", ".mp-listing-item", "li.mp-Listing-item"]
                    for alt_sel in alt_selectors:
                        cards = soup.select(alt_sel)
                        if len(cards) > 0:
                            break
                
                for c in cards[:request.max_results_per_query or 20]:
                    a = c.select_one(SEL["link"])
                    if not a:
                        continue
                    href = a.get("href", "")
                    if not href or not isinstance(href, str):
                        continue
                    full_url = href if href.startswith("http") else urljoin(BASE, href)
                    lid = extract_id(full_url)
                    if lid in seen:
                        continue
                    seen.add(lid)

                    # Try multiple selectors for each field
                    title_el = c.select_one(SEL["title"]) or c.select_one("h3") or c.select_one(".hz-Listing-title")
                    price_el = c.select_one(SEL["price"]) or c.select_one(".hz-Listing-price") or c.select_one("[data-testid*='price']")
                    loc_el = c.select_one(SEL["location"]) or c.select_one(".hz-Listing-location") or c.select_one("[data-testid*='location']")
                    date_el = c.select_one(SEL["date"]) or c.select_one(".hz-Listing-date") or c.select_one("[data-testid*='date']")
                    img_el = c.select_one(SEL["image"]) or c.select_one("img")
                    desc_el = c.select_one(SEL["desc"]) or c.select_one(".hz-Listing-description") or c.select_one("[data-testid*='desc']")

                    item = {
                        "id": lid,
                        "url": full_url,
                        "title": title_el.get_text(strip=True) if title_el else "",
                        "price_text": price_el.get_text(strip=True) if price_el else None,
                        "price_eur": parse_price(price_el.get_text(strip=True)) if price_el else None,
                        "location": loc_el.get_text(strip=True) if loc_el else None,
                        "posted_at": date_el.get_text(strip=True) if date_el else None,
                        "image_url": img_el.get("src") if img_el and img_el.has_attr("src") else None,
                        "description": desc_el.get_text(strip=True) if desc_el else None,
                    }
                    items.append(item)

            # Sort items by price (priced items first, lowest price first)
            items.sort(key=lambda x: (x["price_eur"] is None, x["price_eur"] if x["price_eur"] is not None else 1e12))
            
            results[query] = {
                "count": len(items),
                "items": items
            }
            total_items += len(items)
        
        return {
            "total_queries": len(request.queries),
            "total_items": total_items,
            "results": results
        }
        
    except Exception as e:
        logger.error(f"Batch search failed: {e}")
        return {"error": "An error occurred during batch search", "details": str(e)}

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "marktplaats-scraper"}

class PinterestRequest(BaseModel):
    url: str

class NaturalRequest(BaseModel):
    description: str

@app.post("/curate-pinterest")
async def curate_pinterest(request: PinterestRequest):
    """
    Curate furniture from Pinterest board aesthetic
    """
    try:
        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            logger.error(f"Playwright not available: {e}")
            return {
                "title": "Pinterest Feature Temporarily Unavailable",
                "description": "We're working on bringing Pinterest board curation to you. For now, please try describing your dream space using natural language.",
                "pieces": [],
                "error": "playwright_unavailable"
            }
        
        pinterest_url = request.url
        logger.info(f"Curating from Pinterest: {pinterest_url}")
        
        # Extract pin titles/descriptions from Pinterest
        pins_data = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(pinterest_url, timeout=30000)
                await page.wait_for_timeout(3000)
                
                # Scroll to load more pins
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(1500)
                
                # Extract pin data
                pins = await page.query_selector_all('[data-test-id="pin"]')
                logger.info(f"Found {len(pins)} pins")
                
                for pin in pins[:20]:
                    try:
                        title_el = await pin.query_selector('[data-test-id="pin-title"]')
                        desc_el = await pin.query_selector('[data-test-id="pincard-description"]')
                        
                        title = await title_el.inner_text() if title_el else ""
                        desc = await desc_el.inner_text() if desc_el else ""
                        
                        if title or desc:
                            pins_data.append({
                                "title": title,
                                "description": desc
                            })
                    except:
                        continue
                        
            finally:
                await browser.close()
        
        logger.info(f"Extracted {len(pins_data)} pin descriptions")
        
        # Extract furniture keywords from pins
        furniture_keywords = set()
        common_furniture = ["bureau", "desk", "stoel", "chair", "tafel", "table", "kast", "cabinet", 
                           "lamp", "rek", "shelf", "bank", "sofa", "dressoir"]
        
        for pin in pins_data:
            text = f"{pin['title']} {pin['description']}".lower()
            for keyword in common_furniture:
                if keyword in text:
                    furniture_keywords.add(keyword)
        
        # Add style keywords from pins
        style_keywords = []
        all_text = " ".join([f"{p['title']} {p['description']}" for p in pins_data]).lower()
        
        if "vintage" in all_text or "retro" in all_text:
            style_keywords.append("vintage")
        if "teak" in all_text or "wood" in all_text or "hout" in all_text:
            style_keywords.append("teak")
        if "mid century" in all_text or "jaren 60" in all_text:
            style_keywords.append("jaren 60")
        if "scandinavian" in all_text or "scandinavisch" in all_text:
            style_keywords.append("scandinavisch")
        if "minimalist" in all_text or "minimalistisch" in all_text:
            style_keywords.append("minimalistisch")
        
        # Build search queries
        search_queries = []
        if furniture_keywords:
            base_items = list(furniture_keywords)[:3]
            for item in base_items:
                if style_keywords:
                    search_queries.append(f"{item} {style_keywords[0]}")
                else:
                    search_queries.append(item)
        else:
            search_queries = ["vintage bureau", "design stoel", "teak tafel"]
        
        logger.info(f"Search queries: {search_queries}")
        
        # Search Marktplaats
        all_pieces = []
        for query in search_queries[:4]:
            try:
                search_url = f"{BASE}/q/{query}/"
                
                resp = requests.get(search_url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(resp.content, "lxml")
                
                listings = soup.select(SEL["card"])[:5]
                
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
                    
                    if not title_el or not link_el:
                        continue
                    
                    title = title_el.get_text(strip=True)
                    price_text = price_el.get_text(strip=True) if price_el else "Prijs op aanvraag"
                    image_url = img_el.get("src") if img_el and img_el.has_attr("src") else None
                    listing_url = urljoin(BASE, link_el["href"])
                    
                    # Generate provenance/story
                    provenance = ""
                    if "vintage" in title.lower() or "retro" in title.lower():
                        provenance = "A timeless piece with character and history"
                    elif "teak" in title.lower() or "hout" in title.lower():
                        provenance = "Crafted from natural wood, bringing warmth to your space"
                    elif any(year in title.lower() for year in ["jaren 50", "jaren 60", "jaren 70"]):
                        provenance = "Mid-century design from a golden era of craftsmanship"
                    else:
                        provenance = "A carefully selected piece for discerning collectors"
                    
                    all_pieces.append({
                        "title": title,
                        "price": price_text,
                        "image": image_url,
                        "url": listing_url,
                        "provenance": provenance,
                        "description": f"Discovered in Amsterdam's vintage marketplace, this piece embodies the aesthetic you've curated."
                    })
                    
            except Exception as e:
                logger.error(f"Search failed for '{query}': {e}")
                continue
        
        # Create curated response
        style_desc = "minimalist Scandinavian aesthetic" if "scandinavisch" in style_keywords else "vintage design aesthetic"
        
        return {
            "title": "Your Curated Collection",
            "description": f"We've analyzed your Pinterest board and found {len(all_pieces)} exceptional pieces that match your {style_desc}.",
            "pieces": all_pieces[:12]
        }
        
    except Exception as e:
        logger.error(f"Pinterest curation failed: {e}")
        return {"error": "Failed to curate from Pinterest", "details": str(e)}

@app.post("/curate-natural")
async def curate_natural(request: NaturalRequest):
    """
    Curate furniture from natural language description
    """
    try:
        description = request.description.lower()
        logger.info(f"Curating from description: {description[:100]}...")
        
        # Extract furniture types
        furniture_map = {
            "desk": "bureau", "bureau": "bureau",
            "chair": "stoel", "stoel": "stoel",
            "table": "tafel", "tafel": "tafel",
            "cabinet": "kast", "kast": "kast",
            "shelf": "rek", "shelving": "rek", "rek": "rek",
            "sofa": "bank", "couch": "bank", "bank": "bank",
            "lamp": "lamp", "lighting": "lamp",
            "dresser": "dressoir", "dressoir": "dressoir"
        }
        
        furniture_items = []
        for eng, nl in furniture_map.items():
            if eng in description:
                furniture_items.append(nl)
        
        if not furniture_items:
            furniture_items = ["meubels"]
        
        # Extract style keywords
        style_keywords = []
        if any(word in description for word in ["vintage", "retro", "antique"]):
            style_keywords.append("vintage")
        if any(word in description for word in ["scandinavian", "scandinavisch", "nordic"]):
            style_keywords.append("scandinavisch")
        if any(word in description for word in ["mid century", "mid-century", "jaren 60"]):
            style_keywords.append("jaren 60")
        if any(word in description for word in ["minimalist", "minimal", "clean"]):
            style_keywords.append("minimalistisch")
        if any(word in description for word in ["wood", "wooden", "teak", "oak"]):
            style_keywords.append("hout")
        if any(word in description for word in ["industrial", "industrieel"]):
            style_keywords.append("industrieel")
        
        # Build search queries
        search_queries = []
        for item in furniture_items[:3]:
            if style_keywords:
                search_queries.append(f"{item} {style_keywords[0]}")
            else:
                search_queries.append(item)
        
        logger.info(f"Search queries: {search_queries}")
        
        # Search Marktplaats
        all_pieces = []
        for query in search_queries[:5]:
            try:
                search_url = f"{BASE}/q/{query}/"
                
                resp = requests.get(search_url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(resp.content, "lxml")
                
                listings = soup.select(SEL["card"])[:6]
                
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
                    
                    if not title_el or not link_el:
                        continue
                    
                    title = title_el.get_text(strip=True)
                    price_text = price_el.get_text(strip=True) if price_el else "Prijs op aanvraag"
                    image_url = img_el.get("src") if img_el and img_el.has_attr("src") else None
                    listing_url = urljoin(BASE, link_el["href"])
                    
                    # Generate boutique-style description
                    provenance = ""
                    if "vintage" in title.lower():
                        provenance = "A treasured vintage piece with authentic patina"
                    elif "design" in title.lower():
                        provenance = "Designer craftsmanship meets timeless elegance"
                    elif any(wood in title.lower() for wood in ["teak", "eiken", "oak"]):
                        provenance = "Natural materials showcase expert woodworking"
                    else:
                        provenance = "Carefully curated for your unique vision"
                    
                    all_pieces.append({
                        "title": title,
                        "price": price_text,
                        "image": image_url,
                        "url": listing_url,
                        "provenance": provenance,
                        "description": "This piece aligns beautifully with the aesthetic you've described."
                    })
                    
            except Exception as e:
                logger.error(f"Search failed for '{query}': {e}")
                continue
        
        return {
            "title": "Your Personalized Collection",
            "description": f"Based on your vision, we've curated {len(all_pieces)} exceptional pieces that bring your dream space to life.",
            "pieces": all_pieces[:12]
        }
        
    except Exception as e:
        logger.error(f"Natural language curation failed: {e}")
        return {"error": "Failed to curate collection", "details": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)