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
    city: Optional[str] = "amsterdam"

class NaturalRequest(BaseModel):
    description: str
    city: Optional[str] = "amsterdam"

def extract_aesthetic_keywords(text_lower):
    """Extract specific aesthetic/style keywords from text"""
    aesthetics = {
        "mid_century": ["mid-century", "mid century", "jaren 50", "jaren 60", "50s", "60s", "mcm"],
        "scandinavian": ["scandinavian", "scandi", "nordic", "scandinavisch", "deens", "zweeds"],
        "industrial": ["industrial", "industrieel", "factory", "metaal", "staal"],
        "minimalist": ["minimal", "minimalist", "clean", "minimalistisch", "simpel"],
        "boho": ["boho", "bohemian", "eclectic", "bohemien"],
        "modern": ["modern", "contemporary", "eigentijds"],
        "rustic": ["rustic", "farmhouse", "landelijk", "rustiek"]
    }
    
    materials = {
        "teak": ["teak", "teakhout"],
        "oak": ["oak", "eiken", "eikenhout"],
        "walnut": ["walnut", "walnoot", "notenhout"],
        "wood": ["wood", "hout", "houten"],
        "metal": ["metal", "metaal", "staal", "ijzer"],
        "leather": ["leather", "leer", "leren"]
    }
    
    found_aesthetics = []
    found_materials = []
    
    for key, keywords in aesthetics.items():
        if any(kw in text_lower for kw in keywords):
            found_aesthetics.append(key)
    
    for key, keywords in materials.items():
        if any(kw in text_lower for kw in keywords):
            found_materials.append(key)
    
    return found_aesthetics, found_materials

def generate_specific_queries(furniture_types, aesthetics, materials):
    """Generate specific, aesthetic-focused search queries in Dutch"""
    
    # Dutch style translations (more specific than generic "vintage")
    dutch_styles = {
        "mid_century": ["jaren 60", "mid century", "retro"],
        "scandinavian": ["scandinavisch", "deens design"],
        "industrial": ["industrieel", "industriële"],
        "minimalist": ["minimalistisch", "modern"],
        "boho": ["bohemian"],
        "modern": ["modern design"],
        "rustic": ["landelijk"]
    }
    
    # Dutch material translations
    dutch_materials = {
        "teak": ["teakhout", "teak"],
        "oak": ["eikenhout", "eiken"],
        "walnut": ["notenhout"],
        "wood": ["houten"],
        "metal": ["metaal"],
        "leather": ["leren"]
    }
    
    queries = []
    
    # Strategy: Combine furniture + style + material for very specific queries
    for furniture in furniture_types[:2]:  # Limit to 2 furniture types
        # Add style-specific queries
        for aesthetic in aesthetics[:2]:  # Top 2 aesthetics
            if aesthetic in dutch_styles:
                style_term = dutch_styles[aesthetic][0]
                queries.append(f"{furniture} {style_term}")
        
        # Add material-specific queries
        for material in materials[:1]:  # Top material
            if material in dutch_materials:
                material_term = dutch_materials[material][0]
                queries.append(f"{furniture} {material_term}")
    
    # If no specific styles found, use design/vintage as fallback
    if not queries:
        for furniture in furniture_types[:2]:
            queries.append(f"{furniture} design")
    
    return list(set(queries))[:5]  # Dedupe and limit to 5

@app.post("/curate-pinterest")
async def curate_pinterest(request: PinterestRequest):
    """
    Curate furniture from Pinterest board aesthetic
    Uses URL-based style extraction since Playwright browser dependencies aren't available
    """
    try:
        pinterest_url = request.url
        logger.info(f"Curating from Pinterest URL: {pinterest_url}")
        
        # Extract style hints from URL
        url_lower = pinterest_url.lower()
        furniture_keywords = set()
        
        # Detect furniture types from URL
        if any(word in url_lower for word in ["office", "workspace", "desk", "study", "bureau"]):
            furniture_keywords.update(["bureau", "stoel"])
        if any(word in url_lower for word in ["dining", "eetkamer", "table", "tafel"]):
            furniture_keywords.update(["eettafel", "eetkamerstoel"])
        if any(word in url_lower for word in ["living", "woonkamer", "sofa", "bank"]):
            furniture_keywords.update(["bank", "salontafel", "kast"])
        if any(word in url_lower for word in ["bedroom", "slaapkamer", "bed"]):
            furniture_keywords.update(["bed", "nachtkastje"])
        if any(word in url_lower for word in ["shelv", "kast", "storage", "opberg"]):
            furniture_keywords.update(["kast", "boekenkast"])
        
        # Default to common vintage furniture if nothing detected
        if not furniture_keywords:
            furniture_keywords = {"bureau", "stoel", "kast"}
        
        # Extract aesthetic keywords
        aesthetics, materials = extract_aesthetic_keywords(url_lower)
        
        # Generate specific search queries
        search_queries = generate_specific_queries(
            list(furniture_keywords), 
            aesthetics, 
            materials
        )
        
        logger.info(f"Pinterest aesthetic analysis - Styles: {aesthetics}, Materials: {materials}")
        logger.info(f"Generated search queries: {search_queries}")
        
        # Search Marktplaats
        all_pieces = []
        # Map cities to postal codes for location filtering
        city_postcodes = {
            "amsterdam": "1012AB",
            "rotterdam": "3011AD",
            "den-haag": "2511AA",
            "utrecht": "3511AA",
            "eindhoven": "5611AA",
            "groningen": "9711AA",
            "tilburg": "5011AA",
            "almere": "1311AA"
        }
        postcode = city_postcodes.get(request.city, "1012AB")
        
        for query in search_queries[:4]:
            try:
                # Marktplaats URL format: /z.html with postcode and distance filter
                search_url = f"{BASE}/z.html"
                params = {
                    "query": query,
                    "postcode": postcode,
                    "distanceMeters": 10000
                }
                logger.info(f"Searching {request.city} ({postcode}): {query}")
                
                resp = requests.get(search_url, params=params, headers=HEADERS, timeout=10)
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
                    loc_el = listing.select_one(SEL["location"])
                    desc_el = listing.select_one(SEL["desc"])
                    
                    if not title_el or not link_el:
                        continue
                    
                    title = title_el.get_text(strip=True)
                    price_text = price_el.get_text(strip=True) if price_el else "Prijs op aanvraag"
                    image_url = img_el.get("src") if img_el and img_el.has_attr("src") else None
                    listing_url = urljoin(BASE, link_el["href"])
                    location = loc_el.get_text(strip=True) if loc_el else "Amsterdam"
                    description = desc_el.get_text(strip=True)[:120] if desc_el else "Vintage find from Amsterdam's marketplace"
                    
                    all_pieces.append({
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
        
        # Create curated response with specific style description
        if "scandinavian" in aesthetics:
            style_desc = "Scandinavian aesthetic"
        elif "mid_century" in aesthetics:
            style_desc = "mid-century modern aesthetic"
        elif "industrial" in aesthetics:
            style_desc = "industrial aesthetic"
        elif "minimalist" in aesthetics:
            style_desc = "minimalist aesthetic"
        else:
            style_desc = "design aesthetic"
        
        return {
            "title": "Your Curated Collection",
            "description": f"We've analyzed your Pinterest board and found {len(all_pieces)} pieces that match your {style_desc}.",
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
            "dresser": "dressoir", "dressoir": "dressoir",
            "storage": "opbergruimte", "opslag": "opbergruimte",
            "dining": "eettafel", "eettafel": "eettafel"
        }
        
        furniture_items = []
        for eng, nl in furniture_map.items():
            if eng in description:
                furniture_items.append(nl)
        
        if not furniture_items:
            furniture_items = ["meubels"]
        
        # Use improved aesthetic extraction
        aesthetics, materials = extract_aesthetic_keywords(description)
        
        # Generate specific search queries
        search_queries = generate_specific_queries(
            list(set(furniture_items)),  # Dedupe furniture items
            aesthetics,
            materials
        )
        
        logger.info(f"Natural language aesthetic analysis - Styles: {aesthetics}, Materials: {materials}")
        logger.info(f"Generated search queries: {search_queries}")
        
        # Search Marktplaats
        all_pieces = []
        # Map cities to postal codes for location filtering
        city_postcodes = {
            "amsterdam": "1012AB",
            "rotterdam": "3011AD",
            "den-haag": "2511AA",
            "utrecht": "3511AA",
            "eindhoven": "5611AA",
            "groningen": "9711AA",
            "tilburg": "5011AA",
            "almere": "1311AA"
        }
        postcode = city_postcodes.get(request.city, "1012AB")
        
        for query in search_queries[:5]:
            try:
                # Marktplaats URL format: /z.html with postcode and distance filter
                search_url = f"{BASE}/z.html"
                params = {
                    "query": query,
                    "postcode": postcode,
                    "distanceMeters": 10000
                }
                logger.info(f"Searching {request.city} ({postcode}): {query}")
                
                resp = requests.get(search_url, params=params, headers=HEADERS, timeout=10)
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
                    loc_el = listing.select_one(SEL["location"])
                    desc_el = listing.select_one(SEL["desc"])
                    
                    if not title_el or not link_el:
                        continue
                    
                    title = title_el.get_text(strip=True)
                    price_text = price_el.get_text(strip=True) if price_el else "Prijs op aanvraag"
                    image_url = img_el.get("src") if img_el and img_el.has_attr("src") else None
                    listing_url = urljoin(BASE, link_el["href"])
                    location = loc_el.get_text(strip=True) if loc_el else "Amsterdam"
                    description = desc_el.get_text(strip=True)[:120] if desc_el else "Vintage piece from Amsterdam's marketplace"
                    
                    all_pieces.append({
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