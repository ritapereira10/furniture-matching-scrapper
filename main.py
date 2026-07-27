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
import uuid
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
from marktplaats import (
    BASE,
    HEADERS,
    SEL,
    CITY_POSTCODES,
    CITY_REGIONS,
    parse_price,
    extract_id,
    is_location_in_city_region,
    search_marktplaats_listings,
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


def init_db():
    """Create tables if they don't exist yet. Safe to run on every startup."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id SERIAL PRIMARY KEY,
            session_id TEXT,
            rating TEXT,
            feedback_text TEXT,
            style_profile JSONB,
            search_query TEXT,
            results_count INTEGER,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            city TEXT NOT NULL,
            style_profile JSONB,
            search_queries JSONB,
            source_url TEXT,
            unsubscribe_token TEXT UNIQUE NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now(),
            last_sent_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_listings (
            id SERIAL PRIMARY KEY,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            listing_id TEXT NOT NULL,
            sent_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (subscription_id, listing_id)
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


@app.on_event("startup")
def on_startup():
    try:
        init_db()
        logger.info("Database schema verified/created")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")


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


class SubscribeRequest(BaseModel):
    email: str
    city: Optional[str] = "amsterdam"
    style_profile: Optional[dict] = None
    source_url: Optional[str] = None


@app.post("/subscribe")
async def subscribe(request: SubscribeRequest):
    """
    Turn a curated result into a standing weekly-digest subscription.
    Stores the style profile + derived search queries so weekly_digest.py
    can re-scrape and email only new matches.
    """
    email = (request.email or "").strip()
    if not email or "@" not in email:
        return {"success": False, "message": "Please enter a valid email address"}

    style_profile = request.style_profile or {}
    search_queries = style_profile_to_queries(style_profile) if style_profile else []
    token = uuid.uuid4().hex

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO subscriptions (email, city, style_profile, search_queries, source_url, unsubscribe_token)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            email,
            request.city or "amsterdam",
            Json(style_profile),
            Json(search_queries),
            request.source_url,
            token,
        ))

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"New subscription: {email} ({request.city})")
        return {"success": True, "message": "You're in! Check your inbox soon."}

    except Exception as e:
        logger.error(f"Failed to store subscription: {e}")
        return {"success": False, "message": "Failed to subscribe, please try again"}


@app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(request: Request, token: str = Query(...)):
    """Deactivate a subscription via its unsubscribe token."""
    status = "invalid"
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "UPDATE subscriptions SET is_active = FALSE WHERE unsubscribe_token = %s RETURNING id",
            (token,)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        status = "ok" if row else "invalid"

    except Exception as e:
        logger.error(f"Failed to unsubscribe token {token}: {e}")
        status = "error"

    return templates.TemplateResponse("unsubscribe.html", {"request": request, "status": status})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)