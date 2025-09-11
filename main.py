from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
from typing import Optional, List
import logging
import os
import json
from openai import OpenAI

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
def read_root():
    """Serve the main search interface"""
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Search Interface Not Found</h1><p>Please ensure templates/index.html exists.</p>")

@app.get("/api")
def api_info():
    """API information endpoint"""
    return {
        "service": "Marktplaats Scraper API",
        "version": "1.0.0",
        "endpoints": {
            "main": "/",
            "single_search": "/scrape?query={search_term}&pages={number}",
            "batch_search": "POST /batch-search",
            "smart_search": "POST /smart-search",
            "health_check": "/health",
            "documentation": "/docs"
        },
        "description": "API for scraping Marktplaats listings with smart natural language search"
    }

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

class SmartSearchRequest(BaseModel):
    query: str

class StyleCollectionRequest(BaseModel):
    style: str

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

            for p in range(1, 2):
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

def parse_natural_language_query(query: str) -> dict:
    """Parse natural language search query with English-Dutch translation for maximum results"""
    
    # Comprehensive English-Dutch translation mappings
    furniture_translations = {
        'chair': ['stoel', 'stoelen'],
        'armchair': ['fauteuil', 'fauteuils'],
        'sofa': ['bank', 'banken'],
        'couch': ['bank', 'banken'],
        'sideboard': ['dressoir', 'dressoirs'],
        'cabinet': ['kast', 'kasten'],
        'table': ['tafel', 'tafels'],
        'dining table': ['eettafel', 'eettafels'],
        'coffee table': ['salontafel', 'salontafels'],
        'end table': ['bijzettafel', 'bijzettafels'],
        'side table': ['bijzettafel', 'bijzettafels'],
        'lamp': ['lamp', 'lampen'],
        'floor lamp': ['vloerlamp', 'vloerlampen'],
        'pendant lamp': ['hanglamp', 'hanglampen'],
        'mirror': ['spiegel', 'spiegels'],
        'stool': ['kruk', 'krukken'],
        'desk': ['bureau', 'bureaus'],
        'shelf': ['plank', 'planken'],
        'bookshelf': ['boekenkast', 'boekenkasten'],
        'painting': ['schilderij', 'schilderijen'],
        'artwork': ['kunstwerk', 'kunstwerken'],
        'rug': ['vloerkleed', 'vloerkleden', 'tapijt', 'tapijten']
    }
    
    style_translations = {
        'mid century': ['mid century', 'mcm', 'jaren 60', 'teak', 'palissander', 'vintage'],
        'scandi': ['scandinavisch', 'scandi', 'minimalistisch', 'licht hout', 'beige'],
        'scandinavian': ['scandinavisch', 'scandi', 'minimalistisch', 'licht hout', 'beige'],
        'japandi': ['japandi', 'eiken', 'licht hout', 'minimalistisch'],
        'industrial': ['industrieel', 'metaal', 'staal', 'hout en metaal'],
        'vintage': ['vintage', 'retro', 'oude'],
        'boho': ['boho', 'rotan', 'riet', 'bamboe'],
        'modern': ['modern', 'hedendaags', 'eigentijds'],
        'antique': ['antiek', 'antieke', 'oude'],
        'minimalist': ['minimalistisch', 'minimaal', 'simpel'],
        'rustic': ['rustiek', 'landelijk', 'boerenhuisstijl']
    }
    
    color_translations = {
        'red': ['rood', 'rode'],
        'blue': ['blauw', 'blauwe'],
        'green': ['groen', 'groene'],
        'yellow': ['geel', 'gele'],
        'orange': ['oranje'],
        'purple': ['paars', 'paarse'],
        'pink': ['roze'],
        'black': ['zwart', 'zwarte'],
        'white': ['wit', 'witte'],
        'grey': ['grijs', 'grijze'],
        'gray': ['grijs', 'grijze'],
        'brown': ['bruin', 'bruine'],
        'beige': ['beige'],
        'cream': ['crème', 'creme'],
        'gold': ['goud', 'gouden'],
        'silver': ['zilver', 'zilveren'],
        'bronze': ['brons', 'bronzen'],
        'copper': ['koper', 'koperen'],
        'ivory': ['ivoor', 'ivoren'],
        'teal': ['turquoise'],
        'burgundy': ['bordeaux'],
        'mustard': ['mosterd', 'mosterdgeel'],
        'terracotta': ['terracotta'],
        'olive': ['olijf', 'olijfgroen']
    }
    
    # Parse basic parameters
    query_lower = query.lower()
    
    # Extract max price
    max_price = None
    price_patterns = [
        r'max (\d+) eur',
        r'onder (\d+) eur',
        r'tot (\d+) eur',
        r'max (\d+)',
        r'(\d+) eur max',
        r'maximum (\d+)'
    ]
    for pattern in price_patterns:
        match = re.search(pattern, query_lower)
        if match:
            max_price = int(match.group(1))
            break
    
    # Extract location
    location = None
    dutch_cities = ['amsterdam', 'rotterdam', 'utrecht', 'eindhoven', 'tilburg', 'groningen', 'almere', 'breda', 'nijmegen', 'haarlem', 'enschede', 'apeldoorn', 'arnhem', 'zaanstad', 'den haag', 'haag', 'maastricht', 'dordrecht', 'leiden', 'zoetermeer']
    for city in dutch_cities:
        if city in query_lower:
            location = city
            break
    
    # Extract distance
    radius_km = None
    km_match = re.search(r'(\d+)\s*km', query_lower)
    if km_match:
        radius_km = int(km_match.group(1))
    
    # Enhanced search term building with translations
    search_terms_set = set()
    
    # Start with original query words (cleaned)
    cleaned_query = query_lower
    # Remove price patterns
    for pattern in [r'max \d+ eur[o]?', r'onder \d+ eur[o]?', r'tot \d+ eur[o]?', r'\d+ eur[o]?', r'maximum \d+']:
        cleaned_query = re.sub(pattern, '', cleaned_query)
    # Remove distance patterns
    cleaned_query = re.sub(r'\d+\s*km', '', cleaned_query)
    # Remove common phrases
    for phrase in ['find me', 'looking for', 'zoek', 'van me', 'from me', 'in de buurt']:
        cleaned_query = cleaned_query.replace(phrase, '')
    
    # Add original terms
    original_words = cleaned_query.split()
    search_terms_set.update(original_words)
    
    # Add furniture translations
    for english_term, dutch_terms in furniture_translations.items():
        if english_term in query_lower:
            search_terms_set.update(dutch_terms)
    
    # Add style translations
    detected_style = None
    for english_style, dutch_terms in style_translations.items():
        if english_style in query_lower:
            search_terms_set.update(dutch_terms)
            detected_style = english_style
            break
    
    # Add color translations
    for english_color, dutch_terms in color_translations.items():
        if english_color in query_lower:
            search_terms_set.update(dutch_terms)
    
    # Detect item type
    item_type = None
    for english_item, dutch_terms in furniture_translations.items():
        if english_item in query_lower:
            item_type = dutch_terms[0]  # Use first Dutch term as primary
            break
    
    # Remove empty strings and clean up
    search_terms_set = {term.strip() for term in search_terms_set if term.strip()}
    
    # Create final search string
    search_terms = ' '.join(search_terms_set)
    if not search_terms:
        search_terms = query
    
    return {
        "search_terms": search_terms,
        "max_price_eur": max_price,
        "min_price_eur": None,
        "location": location,
        "radius_km": radius_km,
        "item_type": item_type,
        "style": detected_style
    }

@app.post("/smart-search")
def smart_search(request: SmartSearchRequest):
    """Smart search using natural language processing"""
    try:
        # Parse the natural language query
        parsed_query = parse_natural_language_query(request.query)
        logger.info(f"Parsed query: {parsed_query}")
        
        # Use the extracted search terms for Marktplaats search
        search_terms = parsed_query.get("search_terms", request.query)
        
        # Perform the search using existing scrape function logic
        seen = set()
        items: List[dict] = []
        pages = 2  # Search first 2 pages for MVP
        
        for p in range(1, pages + 1):
            url = f"{BASE}/q/{search_terms}/?p={p}"
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select(SEL["card"])
            logger.info(f"Found {len(cards)} cards on page {p} for search terms '{search_terms}'")
            
            if len(cards) == 0:
                alt_selectors = ["li[data-testid='listing-item']", "article[data-testid='listing']", ".hz-Listing", ".mp-listing-item", "li.mp-Listing-item"]
                for alt_sel in alt_selectors:
                    cards = soup.select(alt_sel)
                    if len(cards) > 0:
                        logger.info(f"Using alternative selector '{alt_sel}' - found {len(cards)} cards")
                        break
            
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

                # Extract item details with multiple fallback selectors
                title_el = c.select_one(SEL["title"]) or c.select_one(".hz-Listing-title") or c.select_one("h3") or c.select_one("[data-testid*='title']")
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

        # Filter results based on parsed parameters
        filtered_items = items
        
        # Filter by max price if specified
        if parsed_query.get("max_price_eur"):
            max_price = parsed_query["max_price_eur"]
            filtered_items = [item for item in filtered_items 
                            if item["price_eur"] is None or item["price_eur"] <= max_price]
        
        # Filter by min price if specified
        if parsed_query.get("min_price_eur"):
            min_price = parsed_query["min_price_eur"]
            filtered_items = [item for item in filtered_items 
                            if item["price_eur"] is not None and item["price_eur"] >= min_price]
        
        # Sort by price (priced items first, lowest first)
        filtered_items.sort(key=lambda x: (x["price_eur"] is None, x["price_eur"] if x["price_eur"] is not None else 1e12))
        
        return {
            "query": request.query,
            "parsed_parameters": parsed_query,
            "search_terms": search_terms,
            "total_found": len(items),
            "results_after_filtering": len(filtered_items),
            "results": filtered_items[:20]  # Limit to 20 results for MVP
        }
        
    except Exception as e:
        logger.error(f"Smart search failed: {e}")
        return {"error": "An error occurred during smart search", "details": str(e)}

@app.post("/style-collection")
def get_style_collection(request: StyleCollectionRequest):
    """Get a curated collection of furniture for a specific style"""
    try:
        # Define style search patterns that actually work
        style_patterns = {
            'mid century': {
                'search_terms': ['teak', 'mcm', 'jaren 60'],
                'furniture_types': {
                    'chairs': ['stoel', 'fauteuil'], 
                    'tables': ['tafel', 'salontafel'],
                    'storage': ['kast', 'dressoir'],
                    'lighting': ['lamp']
                }
            },
            'vintage': {
                'search_terms': ['vintage', 'retro'],
                'furniture_types': {
                    'chairs': ['stoel', 'fauteuil'], 
                    'tables': ['tafel'],
                    'storage': ['kast'],
                    'lighting': ['lamp'],
                    'decor': ['spiegel', 'schilderij']
                }
            },
            'industrial': {
                'search_terms': ['industrieel', 'metaal'], 
                'furniture_types': {
                    'chairs': ['stoel'],
                    'tables': ['tafel'],
                    'storage': ['kast'],
                    'lighting': ['lamp']
                }
            },
            'scandi': {
                'search_terms': ['licht hout', 'beige'],
                'furniture_types': {
                    'chairs': ['stoel'],
                    'tables': ['tafel', 'eettafel'],
                    'storage': ['kast'],
                    'lighting': ['lamp']
                }
            }
        }
        
        style_key = request.style.lower()
        if style_key not in style_patterns:
            return {"error": f"Style '{request.style}' not supported", "available_styles": list(style_patterns.keys())}
        
        pattern = style_patterns[style_key]
        collection = {}
        
        # Search for each furniture type with each style term
        for category, furniture_types in pattern['furniture_types'].items():
            category_items = []
            seen_ids = set()
            
            for style_term in pattern['search_terms']:
                for furniture_type in furniture_types:
                    search_query = f"{style_term} {furniture_type}"
                    
                    # Use simplified search logic
                    try:
                        url = f"{BASE}/q/{search_query}/?p=1"
                        r = requests.get(url, headers=HEADERS, timeout=20)
                        r.raise_for_status()
                        
                        soup = BeautifulSoup(r.text, "lxml")
                        cards = soup.select(SEL["card"])
                        
                        if len(cards) == 0:
                            # Try alternative selectors
                            alt_selectors = ["li[data-testid='listing-item']", "article[data-testid='listing']", ".hz-Listing"]
                            for alt_sel in alt_selectors:
                                cards = soup.select(alt_sel)
                                if len(cards) > 0:
                                    break
                        
                        # Process results (limit to 3 per search to avoid overwhelming)
                        for c in cards[:3]:
                            a = c.select_one(SEL["link"])
                            if not a:
                                continue
                            href = a.get("href", "")
                            if not href or not isinstance(href, str):
                                continue
                            full_url = href if href.startswith("http") else urljoin(BASE, href)
                            lid = extract_id(full_url)
                            
                            if lid in seen_ids:
                                continue
                            seen_ids.add(lid)
                            
                            # Extract item details
                            title_el = c.select_one(SEL["title"]) or c.select_one(".hz-Listing-title") or c.select_one("h3")
                            price_el = c.select_one(SEL["price"]) or c.select_one(".hz-Listing-price")
                            loc_el = c.select_one(SEL["location"]) or c.select_one(".hz-Listing-location")
                            img_el = c.select_one(SEL["image"]) or c.select_one("img")
                            
                            item = {
                                "id": lid,
                                "url": full_url,
                                "title": title_el.get_text(strip=True) if title_el else "",
                                "price_text": price_el.get_text(strip=True) if price_el else "",
                                "location": loc_el.get_text(strip=True) if loc_el else "",
                                "image_url": img_el.get("src") or img_el.get("data-src") if img_el else None,
                                "style_match": style_term,
                                "furniture_type": furniture_type
                            }
                            
                            # Parse price for filtering
                            item["price_eur"] = parse_price(item["price_text"])
                            
                            category_items.append(item)
                            
                    except Exception as search_error:
                        logger.warning(f"Search failed for '{search_query}': {search_error}")
                        continue
            
            if category_items:
                # Sort by price (lowest first, null prices last)
                category_items.sort(key=lambda x: (x["price_eur"] is None, x["price_eur"] if x["price_eur"] is not None else 1e12))
                collection[category] = category_items[:6]  # Limit to 6 items per category
        
        return {
            "style": request.style,
            "total_categories": len(collection),
            "collection": collection
        }
        
    except Exception as e:
        logger.error(f"Style collection failed: {e}")
        return {"error": "An error occurred while building style collection", "details": str(e)}

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "marktplaats-scraper"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1, log_level="info")