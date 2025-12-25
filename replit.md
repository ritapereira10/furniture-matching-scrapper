# Overview

**Atelier** is an AI-powered furniture discovery platform that curates Marktplaats listings based on Pinterest board aesthetic analysis OR natural language descriptions. The system uses vision AI to analyze Pinterest images, TF-IDF embeddings for semantic matching, and LLM for explainability.

The experience features bold Gen Z design with playful language that makes vintage furniture hunting fun and engaging.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## AI Pipeline (Core Innovation)

The AI architecture follows a three-seam approach:

1. **Taste Extraction (Vision AI)**
   - Fetches images from Pinterest board URLs
   - Sends to GPT-4o vision for style analysis
   - Returns strict JSON: styles, materials, colors, objects, vibe_keywords, avoid, confidence

2. **Semantic Matching (Embeddings)**
   - TF-IDF vectorization for text similarity (scikit-learn)
   - Per-request vectorizers to avoid global state issues
   - Re-ranks listings by cosine similarity to style profile

3. **Explainability (LLM)**
   - GPT-4o-mini generates "why matches" and "tradeoffs" for top results
   - Concurrent processing with ThreadPoolExecutor
   - Fallback explanations when AI unavailable

## AI Module Structure

- **ai_client.py**: Core AI functions
  - `extract_style(images)` - Vision API for Pinterest images
  - `retrieve_candidates(style_profile, listings)` - TF-IDF similarity ranking
  - `explain_matches(style_profile, listings)` - LLM explanations
  - `style_profile_to_queries(style_profile)` - Converts to Dutch search terms
  - `refine_style(profile, constraints, message)` - Conversational refinement

- **pinterest_scraper.py**: Pinterest image extraction
  - `get_pinterest_images(board_url)` - Fetches board images
  - `extract_style_hints_from_url(url)` - URL-based fallback
  - Caching by URL hash

## Backend Framework
- **FastAPI**: Web framework with automatic API documentation
- **Uvicorn**: ASGI server with hot reload
- **OpenAI Integration**: Replit AI Integrations (no API key required, billed to credits)

## Application Structure
- **Frontend**: Bold Gen Z-styled HTML/CSS via Jinja2 templates
- **Backend**: main.py with FastAPI endpoints
- **AI Module**: ai_client.py for AI functions
- **Pinterest Module**: pinterest_scraper.py for image extraction
- **Development Server**: 0.0.0.0:5000

## Scraping Architecture
- **Production-Ready**: Real data extraction from Marktplaats
- **Adaptive Selectors**: Primary and fallback CSS selectors
- **Deduplication**: Unique ID extraction prevents duplicates
- **Rate Limiting**: Respectful scraping with delays and proper headers

# API Endpoints

## AI-Powered Endpoints
- **POST /curate-pinterest**: Vision AI → style extraction → search → re-rank → explain
- **POST /curate-natural**: Style profile from text → search → re-rank → explain
- **POST /refine**: Conversational refinement of results

## Legacy Endpoints
- **GET /**: Landing page
- **GET /scrape**: Single search with pagination
- **POST /batch-search**: Multiple search queries
- **GET /health**: Health check

# External Dependencies

## Core Dependencies
- **FastAPI**: Web framework
- **Uvicorn**: ASGI server
- **Jinja2**: Template engine
- **BeautifulSoup4**: HTML parsing
- **Requests**: HTTP client
- **lxml**: Fast XML/HTML parser
- **Pydantic**: Data validation
- **OpenAI**: AI integration client
- **scikit-learn**: TF-IDF vectorization and cosine similarity
- **NumPy**: Numerical operations
- **Tenacity**: Retry logic with backoff

## Key Features
- **AI-Powered Curation**: Vision AI analyzes Pinterest boards
- **Semantic Matching**: TF-IDF embeddings rank listings by relevance
- **Explainability**: LLM explains why each piece matches
- **Conversational Refinement**: Update style/constraints via chat
- **Multi-Language Support**: 5 languages (EN, NL, PT, DE, FR)
- **City-Based Filtering**: 8 Dutch cities with 10km radius
- **Graceful Degradation**: Fallbacks when AI unavailable

## Style Profile Schema
```json
{
  "styles": ["mid-century modern", "scandinavian"],
  "materials": ["oak", "teak", "linen"],
  "colors": ["warm wood", "cream", "black accents"],
  "objects": ["dining table", "floor lamp"],
  "vibe_keywords": ["minimal", "warm", "clean lines"],
  "avoid": ["high gloss", "ornate"],
  "confidence": 0.85
}
```

## Fallback Strategy
- All AI functions have fallback returns
- Pinterest extraction falls back to URL-based hints
- Explanations fall back to simple descriptions
- Refinement falls back to keyword parsing
