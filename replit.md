# Overview

**Atelier** is a Gen Z-styled furniture discovery platform that curates Marktplaats listings based on either Pinterest board aesthetic analysis OR natural language descriptions. The experience features bold, vibrant design with playful language that makes vintage furniture hunting fun and engaging.

The system transforms raw marketplace listings into curated "pieces" with immediate price visibility, location info, and real descriptions. Users can either share their Pinterest moodboard or describe their dream space in natural language, and Atelier searches Marktplaats to find matching vintage and designer furniture.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Backend Framework
- **FastAPI**: Chosen as the web framework for its automatic API documentation, type hints support, and high performance
- **Uvicorn**: ASGI server for running the FastAPI application with async support
- **RESTful API Design**: Simple endpoint structure with GET routes for root and scraping operations

## Application Structure
- **Frontend**: Bold Gen Z-styled HTML/CSS interface served via Jinja2 templates
- **Backend**: Single file architecture in `main.py` with FastAPI endpoints
- **Templates**: Gen Z design with chunky fonts (Space Grotesk, DM Sans), vibrant gradients (pink/orange, blue/purple), bold black borders with box shadows, playful casual language
- **Development Server**: Configured to run on host `0.0.0.0` and port `5000` for accessibility

## Scraping Architecture
- **Production-Ready Implementation**: Fully functional scraper that extracts real data from Marktplaats
- **Adaptive Selectors**: Uses primary and fallback CSS selectors to handle website structure changes
- **Batch Processing**: Supports multiple simultaneous searches for Pinterest board matching
- **Data Extraction**: Captures title, price, location, description, images, and direct links
- **Price Parsing**: Handles both fixed prices and negotiable items ("Bieden")
- **Deduplication**: Prevents duplicate listings using unique ID extraction
- **Rate Limiting**: Implements respectful scraping with delays and proper headers

# External Dependencies

## Core Dependencies
- **FastAPI**: Web framework for building the API with automatic documentation
- **Uvicorn**: ASGI server for running the application with hot reload
- **Jinja2**: Template engine for serving HTML interface
- **BeautifulSoup4**: HTML parsing library for extracting listing data
- **Requests**: HTTP client for making web requests to Marktplaats
- **lxml**: Fast XML/HTML parser for BeautifulSoup
- **Pydantic**: Data validation for API request/response models
- **Playwright**: Browser automation for Pinterest scraping (optional, requires system dependencies)

## API Endpoints
- **GET /**: Serves the elegant Atelier landing page with two entry points
- **POST /curate-pinterest**: Analyzes Pinterest board → extracts style DNA → searches Marktplaats → returns curated collection (requires Playwright)
- **POST /curate-natural**: Analyzes natural language description → extracts furniture keywords → searches Marktplaats → returns curated pieces
- **GET /scrape**: Legacy single search with pagination support
- **POST /batch-search**: Legacy batch search endpoint
- **GET /health**: Health check endpoint

## User Experience Flow
1. **Landing Page**: User chooses between Pinterest board URL or natural language description with vibrant gradient cards
2. **Input**: User provides Pinterest URL or describes their dream space with playful prompts
3. **Curation**: Backend analyzes aesthetic, searches Marktplaats, transforms listings into "pieces"
4. **Showroom**: Bold Gen Z-style presentation with immediate price visibility (yellow badges overlaid on images), location labels, real descriptions, and tight grid layout showing more items per page

## Data Transformation
Raw Marktplaats listings are transformed into curated "pieces" with:
- **Real Data**: Actual descriptions from listings (first 120 characters)
- **Location Info**: City/region where item is located
- **Immediate Pricing**: Bold yellow price badges overlaid on images for instant visibility
- **Compact Layout**: Optimized grid showing more items per page (280px min-width vs previous 350px)

## Key Features
- **Dual Input Modes**: Pinterest board URL OR natural language description
- **Aesthetic Analysis**: Extracts style keywords (vintage, Scandinavian, mid-century, teak, etc.)
- **Intelligent Search**: Translates aesthetic preferences into Dutch search queries for Marktplaats
- **Boutique Presentation**: Transforms raw listings into curated "pieces" with storytelling
- **Graceful Degradation**: Pinterest feature gracefully handles missing Playwright dependencies
- **Error Handling**: User-friendly error messages and automatic fallback to natural language mode
- **Logging**: Comprehensive logging for debugging and monitoring

## Known Limitations
- **Pinterest Scraping**: Requires Playwright with chromium system dependencies (nss, dbus, X11 libs) which may not be available in all environments
- **Fallback Strategy**: Pinterest endpoint returns friendly error message when dependencies are unavailable