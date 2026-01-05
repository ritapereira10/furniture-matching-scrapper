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
import psycopg2
from psycopg2.extras import Json

from pinterest_scraper import get_pinterest_images, get_pinterest_image_urls, extract_style_hints_from_url
from ai_client import (
    extract_style,
    retrieve_candidates,
    explain_matches,
    style_profile_to_queries,
    refine_style,
    translate_titles_batch
)

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
    language: Optional[str] = "en"

class NaturalRequest(BaseModel):
    description: str
    city: Optional[str] = "amsterdam"
    language: Optional[str] = "en"

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

def search_marktplaats_listings(queries: list, city: str = "amsterdam", max_per_query: int = 8) -> list:
    """Search Marktplaats and return raw listing data."""
    postcode = CITY_POSTCODES.get(city, "1012AB")
    all_listings = []
    seen_ids = set()
    
    for query in queries[:6]:
        try:
            search_url = f"{BASE}/z.html"
            params = {
                "query": query,
                "postcode": postcode,
                "distanceMeters": 10000
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
    
    return all_listings

@app.post("/curate-pinterest")
async def curate_pinterest(request: PinterestRequest):
    """
    AI-powered Pinterest board curation.
    1. Fetches images from Pinterest board
    2. Uses vision AI to extract style profile
    3. Generates targeted Dutch search queries
    4. Searches Marktplaats
    5. Re-ranks by semantic similarity
    6. Adds AI explanations for top matches
    """
    try:
        pinterest_url = request.url
        logger.info(f"AI-powered curation from Pinterest: {pinterest_url}")
        
        use_ai = True
        style_profile = None
        
        pinterest_images = get_pinterest_images(pinterest_url, max_images=10)
        
        if pinterest_images:
            logger.info(f"Got {len(pinterest_images)} Pinterest images, running vision AI")
            style_profile = extract_style(pinterest_images)
            logger.info(f"AI style profile: {style_profile}")
        else:
            logger.warning("No Pinterest images, falling back to URL-based extraction")
            use_ai = False
            url_hints = extract_style_hints_from_url(pinterest_url)
            style_profile = {
                "styles": url_hints.get("styles", ["vintage"]),
                "materials": url_hints.get("materials", ["wood"]),
                "colors": ["natural"],
                "objects": url_hints.get("objects", ["furniture"]),
                "vibe_keywords": ["classic"],
                "avoid": [],
                "confidence": 0.3
            }
        
        search_queries = style_profile_to_queries(style_profile)
        logger.info(f"Generated search queries: {search_queries}")
        
        all_listings = search_marktplaats_listings(search_queries, request.city or "amsterdam")
        logger.info(f"Found {len(all_listings)} total listings")
        
        if not all_listings:
            return {
                "title": "No Matches Found",
                "description": "We couldn't find any items matching your aesthetic. Try a different Pinterest board or check back later.",
                "pieces": [],
                "style_profile": style_profile,
                "ai_powered": use_ai
            }
        
        if use_ai and len(all_listings) > 5:
            top_candidates = retrieve_candidates(style_profile, all_listings, top_k=15)
            logger.info(f"Re-ranked to {len(top_candidates)} top candidates")
        else:
            top_candidates = all_listings[:15]
        
        final_pieces = top_candidates[:12]
        
        if use_ai and len(final_pieces) > 0:
            try:
                final_pieces = explain_matches(style_profile, final_pieces[:8])
                logger.info("Added AI explanations to top matches")
            except Exception as e:
                logger.warning(f"Explanation generation failed: {e}")
        
        target_lang = request.language or "en"
        if target_lang != "nl" and final_pieces:
            try:
                titles = [p.get("title", "") for p in final_pieces]
                translated = translate_titles_batch(titles, target_lang)
                for i, piece in enumerate(final_pieces):
                    if i < len(translated):
                        piece["title_translated"] = translated[i]
                        piece["title_original"] = piece.get("title", "")
                logger.info(f"Translated {len(translated)} titles to {target_lang}")
            except Exception as e:
                logger.warning(f"Title translation failed: {e}")
        
        style_names = style_profile.get("styles", [])
        if style_names:
            style_desc = ", ".join(style_names[:2]) + " aesthetic"
        else:
            style_desc = "curated aesthetic"
        
        return {
            "title": "Your Curated Collection",
            "description": f"We analyzed your Pinterest board and found {len(final_pieces)} pieces that match your {style_desc}.",
            "pieces": final_pieces,
            "style_profile": style_profile,
            "ai_powered": use_ai,
            "pinterest_images": get_pinterest_image_urls(pinterest_url, max_urls=6)
        }
        
    except Exception as e:
        logger.error(f"Pinterest curation failed: {e}")
        return {"error": "Failed to curate from Pinterest", "details": str(e)}

@app.post("/curate-natural")
async def curate_natural(request: NaturalRequest):
    """
    AI-powered natural language curation.
    Converts description to style profile and searches accordingly.
    """
    try:
        description = request.description.lower()
        logger.info(f"Curating from description: {description[:100]}...")
        
        furniture_map = {
            "desk": "desk", "bureau": "desk",
            "chair": "chair", "stoel": "chair",
            "table": "dining table", "tafel": "dining table",
            "cabinet": "cabinet", "kast": "cabinet",
            "shelf": "shelf", "shelving": "shelf", "rek": "shelf",
            "sofa": "sofa", "couch": "sofa", "bank": "sofa",
            "lamp": "lamp", "lighting": "lamp",
            "dresser": "dresser", "dressoir": "dresser",
            "storage": "cabinet", "opslag": "cabinet",
            "dining": "dining table", "eettafel": "dining table",
            "bed": "bed", "slaapkamer": "bed"
        }
        
        found_objects = []
        for eng, obj_type in furniture_map.items():
            if eng in description:
                found_objects.append(obj_type)
        
        if not found_objects:
            found_objects = ["furniture"]
        
        aesthetics, mat = extract_aesthetic_keywords(description)
        
        style_profile = {
            "styles": [a.replace("_", "-") for a in aesthetics] if aesthetics else ["vintage"],
            "materials": mat if mat else ["wood"],
            "colors": ["natural"],
            "objects": list(set(found_objects)),
            "vibe_keywords": ["curated"],
            "avoid": [],
            "confidence": 0.6
        }
        
        search_queries = style_profile_to_queries(style_profile)
        logger.info(f"Natural language style profile: {style_profile}")
        logger.info(f"Generated search queries: {search_queries}")
        
        all_listings = search_marktplaats_listings(search_queries, request.city or "amsterdam")
        logger.info(f"Found {len(all_listings)} listings")
        
        if not all_listings:
            return {
                "title": "No Matches Found",
                "description": "We couldn't find any items matching your description. Try different keywords or check back later.",
                "pieces": [],
                "style_profile": style_profile
            }
        
        if len(all_listings) > 5:
            top_candidates = retrieve_candidates(style_profile, all_listings, top_k=15)
        else:
            top_candidates = all_listings
        
        final_pieces = top_candidates[:12]
        
        if len(final_pieces) > 0:
            try:
                final_pieces = explain_matches(style_profile, final_pieces[:8])
            except Exception as e:
                logger.warning(f"Explanation generation failed: {e}")
        
        target_lang = request.language or "en"
        if target_lang != "nl" and final_pieces:
            try:
                titles = [p.get("title", "") for p in final_pieces]
                translated = translate_titles_batch(titles, target_lang)
                for i, piece in enumerate(final_pieces):
                    if i < len(translated):
                        piece["title_translated"] = translated[i]
                        piece["title_original"] = piece.get("title", "")
            except Exception as e:
                logger.warning(f"Title translation failed: {e}")
        
        return {
            "title": "Your Personalized Collection",
            "description": f"Based on your vision, we've curated {len(final_pieces)} pieces that bring your dream space to life.",
            "pieces": final_pieces,
            "style_profile": style_profile
        }
        
    except Exception as e:
        logger.error(f"Natural language curation failed: {e}")
        return {"error": "Failed to curate collection", "details": str(e)}


class RefineRequest(BaseModel):
    style_profile: dict
    constraints: Optional[dict] = {}
    message: str
    city: Optional[str] = "amsterdam"

@app.post("/refine")
async def refine_results(request: RefineRequest):
    """
    Refine search results based on user feedback.
    Updates style profile and/or constraints and re-searches.
    """
    try:
        logger.info(f"Refining with message: {request.message}")
        
        updated_style, updated_constraints = refine_style(
            request.style_profile,
            request.constraints or {},
            request.message
        )
        
        search_queries = style_profile_to_queries(updated_style)
        all_listings = search_marktplaats_listings(search_queries, request.city or "amsterdam")
        
        price_max = updated_constraints.get("price_max")
        if price_max:
            filtered = []
            for listing in all_listings:
                price_text = listing.get("price", "")
                try:
                    price_num = float(re.sub(r'[^\d.]', '', price_text.replace(',', '.')))
                    if price_num <= price_max:
                        filtered.append(listing)
                except:
                    filtered.append(listing)
            all_listings = filtered
        
        if len(all_listings) > 5:
            top_candidates = retrieve_candidates(updated_style, all_listings, top_k=15)
        else:
            top_candidates = all_listings
        
        final_pieces = top_candidates[:12]
        
        return {
            "title": "Refined Collection",
            "description": f"Based on your feedback, we found {len(final_pieces)} updated matches.",
            "pieces": final_pieces,
            "style_profile": updated_style,
            "constraints": updated_constraints
        }
        
    except Exception as e:
        logger.error(f"Refinement failed: {e}")
        return {"error": "Failed to refine results", "details": str(e)}


class FeedbackRequest(BaseModel):
    rating: str
    feedback_text: Optional[str] = None
    style_profile: Optional[dict] = None
    search_query: Optional[str] = None
    results_count: Optional[int] = None
    session_id: Optional[str] = None


def get_db_connection():
    """Get a database connection."""
    return psycopg2.connect(os.environ.get("DATABASE_URL"))


@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Store user feedback about AI curation results.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO feedback (session_id, rating, feedback_text, style_profile, search_query, results_count)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.session_id,
            request.rating,
            request.feedback_text,
            Json(request.style_profile) if request.style_profile else None,
            request.search_query,
            request.results_count
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Feedback stored: {request.rating}")
        return {"success": True, "message": "Thank you for your feedback!"}
        
    except Exception as e:
        logger.error(f"Failed to store feedback: {e}")
        return {"success": False, "message": "Failed to save feedback"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)