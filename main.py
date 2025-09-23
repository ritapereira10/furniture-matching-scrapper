from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
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

def translate_dutch_title_to_english(dutch_title):
    """Translate Dutch furniture titles to English for better UX"""
    if not dutch_title:
        return dutch_title
    
    # Common Dutch-English furniture translations
    translations = {
        # Furniture types
        'stoel': 'chair',
        'stoelen': 'chairs', 
        'fauteuil': 'armchair',
        'fauteuils': 'armchairs',
        'tafel': 'table',
        'tafels': 'tables',
        'salontafel': 'coffee table',
        'eettafel': 'dining table',
        'bijzettafel': 'side table',
        'bureau': 'desk',
        'kast': 'cabinet',
        'kasten': 'cabinets',
        'lamp': 'lamp',
        'lampen': 'lamps',
        'hanglamp': 'pendant lamp',
        'vloerlamp': 'floor lamp',
        'bank': 'sofa',
        'banken': 'sofas',
        'spiegel': 'mirror',
        'spiegels': 'mirrors',
        'kruk': 'stool',
        'krukken': 'stools',
        'rek': 'rack',
        'rekken': 'racks',
        'wandrek': 'wall rack',
        
        # Materials
        'teak': 'teak wood',
        'teakhouk': 'teak wood', 
        'teakhout': 'teak wood',
        'hout': 'wood',
        'houten': 'wooden',
        'massief': 'solid',
        'fluweel': 'velvet',
        'leder': 'leather',
        'leer': 'leather', 
        'metaal': 'metal',
        'ijzer': 'iron',
        'staal': 'steel',
        'glas': 'glass',
        'glazen': 'glass',
        
        # Styles & descriptors
        'vintage': 'vintage',
        'retro': 'retro',
        'industrieel': 'industrial',
        'industriële': 'industrial',
        'jaren 60': '1960s',
        'jaren 70': '1970s',
        'scandinavisch': 'Scandinavian',
        'minimalistisch': 'minimalist',
        'modern': 'modern',
        'antiek': 'antique',
        'klassiek': 'classic',
        'design': 'design',
        
        # Common words
        'met': 'with',
        'zonder': 'without', 
        'groot': 'large',
        'kleine': 'small',
        'nieuwe': 'new',
        'nieuw': 'new',
        'oude': 'old',
        'oud': 'old',
        'originele': 'original',
        'origineel': 'original',
        'prachtige': 'beautiful',
        'prachtig': 'beautiful',
        'unieke': 'unique',
        'uniek': 'unique',
        'betrouwbaar': 'reliable',
        'nauwkeurig': 'accurate',
        'weegschaal': 'scale',
        'dienblad': 'tray',
        'bekers': 'cups',
        'laden': 'drawers',
        'planken': 'shelves',
        'vormig': 'shaped',
        'hoekbureau': 'corner desk',
        'klaptafel': 'folding table',
        'rond': 'round',
        'stapelbaar': 'stackable',
        'inklapbare': 'foldable',
        'tuintafel': 'garden table'
    }
    
    # Convert to lowercase for translation, preserve original case structure
    lower_title = dutch_title.lower()
    translated_words = []
    
    # Split on common delimiters and translate each part
    import re
    words = re.findall(r'\b\w+\b', dutch_title)
    
    for word in words:
        lower_word = word.lower()
        if lower_word in translations:
            # Try to preserve capitalization
            if word.isupper():
                translated_words.append(translations[lower_word].upper())
            elif word.istitle():
                translated_words.append(translations[lower_word].title())
            else:
                translated_words.append(translations[lower_word])
        else:
            translated_words.append(word)
    
    # Rejoin with appropriate spacing
    result = ' '.join(translated_words)
    
    # Clean up common patterns
    result = re.sub(r'\s*-\s*', ' - ', result)  # Standardize dashes
    result = re.sub(r'\s+', ' ', result)  # Remove extra spaces
    result = result.strip()
    
    return result if result != dutch_title else dutch_title

def translate_price_text_to_english(dutch_price_text):
    """Translate Dutch price terms to English"""
    if not dutch_price_text:
        return dutch_price_text
    
    price_translations = {
        'bieden': 'Negotiable',
        'gratis': 'Free', 
        'vraagprijs': 'Asking price',
        'vanaf': 'From',
        'per': 'per',
        'stuk': 'piece',
        'set': 'set'
    }
    
    # Convert to lowercase for matching, preserve original format
    lower_text = dutch_price_text.lower()
    for dutch_term, english_term in price_translations.items():
        if dutch_term in lower_text:
            return english_term
    
    return dutch_price_text

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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files to serve images and assets
app.mount("/static", StaticFiles(directory="."), name="static")

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
                    "title": translate_dutch_title_to_english(title_el.get_text(strip=True)) if title_el else "",
                    "price_text": translate_price_text_to_english(price_el.get_text(strip=True)) if price_el else None,
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
                        "title": translate_dutch_title_to_english(title_el.get_text(strip=True)) if title_el else "",
                        "price_text": translate_price_text_to_english(price_el.get_text(strip=True)) if price_el else None,
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
        'mid century': ['teak'],  # Simple, proven term
        'scandi': ['scandinavisch'],
        'scandinavian': ['scandinavisch'], 
        'japandi': ['japandi'],
        'industrial': ['industrieel'],
        'vintage': ['vintage'],
        'boho': ['rotan'],
        'modern': ['modern'],
        'antique': ['antiek'],
        'minimalist': ['minimalistisch'],
        'rustic': ['landelijk']
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
    
    # Simple search term building - use proven Dutch terms only
    search_terms_parts = []
    
    # Special handling for specific problematic queries FIRST
    if 'design lamp' in query_lower:
        search_terms_parts = ['hanglamp', 'vloerlamp']  # More specific lamp types
        item_type = 'lamp'
        detected_style = None
    elif 'industrial style' in query_lower:
        search_terms_parts = ['industrieel', 'staal']  # More specific materials
        item_type = None
        detected_style = 'industrial'
    else:
        # Standard detection logic
        # Detect furniture type and add Dutch translation
        item_type = None
        for english_term, dutch_terms in furniture_translations.items():
            if english_term in query_lower:
                search_terms_parts.append(dutch_terms[0])  # Use first Dutch term only
                item_type = dutch_terms[0]
                break
        
        # Detect style and add Dutch translation
        detected_style = None
        for english_style, dutch_terms in style_translations.items():
            if english_style in query_lower:
                search_terms_parts.extend(dutch_terms)  # Add style terms
                detected_style = english_style
                break
        
        # Detect colors and add Dutch translation
        for english_color, dutch_terms in color_translations.items():
            if english_color in query_lower:
                search_terms_parts.append(dutch_terms[0])  # Use first Dutch term only
                break
    
    # Fallback for unmatched queries
    if not search_terms_parts:
        # For common room queries, use simple terms
        if 'living room' in query_lower:
            search_terms_parts = ['woonkamer']
        elif 'bedroom' in query_lower:
            search_terms_parts = ['slaapkamer']
        elif 'dining room' in query_lower:
            search_terms_parts = ['eetkamer']
        else:
            # Use original query as last resort
            search_terms_parts = [query]
    
    # Create final search string (max 3 terms for better results)
    search_terms = ' '.join(search_terms_parts[:3])
    
    # Default to Amsterdam within 10km if no location specified
    if location is None:
        location = "amsterdam"
    if radius_km is None:
        radius_km = 10
    
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
                    "title": translate_dutch_title_to_english(title_el.get_text(strip=True)) if title_el else "",
                    "price_text": translate_price_text_to_english(price_el.get_text(strip=True)) if price_el else None,
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
        
        # Transform to match Style Genie specification with English translation
        formatted_items = []
        for item in filtered_items[:20]:  # Limit to 20 results
            # Translate Dutch title to English for better UX
            title = item.get("title", "")
            english_title = translate_dutch_title_to_english(title)
            
            # Translate price text (Bieden, Gratis, etc.)
            price_text = item.get("price_text", "")
            english_price_text = translate_price_text_to_english(price_text)
            
            # Extract city from location (remove "Netherlands" suffix)
            location = item.get("location", "")
            if location and location.lower().endswith(", nederland"):
                location = location.replace(", Nederland", "").replace(", nederland", "")
            elif location and location.lower() == "heel nederland":
                location = "Netherlands"
            
            formatted_item = {
                "title": english_title,
                "price": item.get("price_eur", 0),
                "price_text": english_price_text,
                "currency": "EUR", 
                "url": item.get("url", ""),
                "image": item.get("image_url", ""),
                "source": "Marktplaats",
                "location": location,
                "distance_km": None,  # Could be calculated based on location in future
                "posted_at": item.get("posted_at", "")
            }
            formatted_items.append(formatted_item)
        
        # Map Dutch item types back to English for UI display
        item_type_mapping = {
            'stoel': 'chair',
            'tafel': 'table', 
            'lamp': 'lamp',
            'bank': 'sofa',
            'kast': 'cabinet',
            'fauteuil': 'chair'
        }
        
        english_item_type = item_type_mapping.get(parsed_query.get("item_type"), parsed_query.get("item_type"))
        
        # Format parsed query to match specification  
        formatted_parsed_query = {
            "item_type": english_item_type,
            "style": parsed_query.get("style"),
            "min_price": parsed_query.get("min_price_eur"),
            "max_price": parsed_query.get("max_price_eur"),
            "city": parsed_query.get("location") or "Amsterdam",  # Default to Amsterdam
            "radius_km": parsed_query.get("radius_km")
        }
        
        # Check if query is too generic and add suggestions
        suggestions = None
        if len(request.query.split()) <= 2 and not any([
            parsed_query.get("style"), 
            parsed_query.get("max_price_eur"), 
            parsed_query.get("location")
        ]):
            suggestions = [
                "vintage style",
                "under €150", 
                "mid century modern",
                "industrial look",
                "in Rotterdam",
                "scandinavian design"
            ]
        
        response = {
            "parsed_query": formatted_parsed_query,
            "items": formatted_items
        }
        
        if suggestions:
            response["suggestions"] = suggestions
            
        return response
        
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
                                "title": translate_dutch_title_to_english(title_el.get_text(strip=True)) if title_el else "",
                                "price_text": translate_price_text_to_english(price_el.get_text(strip=True)) if price_el else "",
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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1, log_level="info")