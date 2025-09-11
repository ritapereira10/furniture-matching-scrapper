# Overview

This is a magical Pinterest board to Marktplaats matching system that combines AI interior design personality with intelligent furniture search. The "Style Genie" provides a personalized, enchanting experience that analyzes natural language queries, searches Marktplaats for matching furniture, and presents results with AI commentary in a beautiful, anticipation-building interface. The system transforms utilitarian marketplace search into a magical, personal experience like "Spotify Wrapped for furniture."

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Backend Framework
- **FastAPI**: Chosen as the web framework for its automatic API documentation, type hints support, and high performance
- **Uvicorn**: ASGI server for running the FastAPI application with async support
- **RESTful API Design**: Simple endpoint structure with GET routes for root and scraping operations

## Application Structure
- **Single File Architecture**: Currently uses a monolithic approach with all functionality in `main.py`
- **Error Handling**: Basic try-catch mechanism implemented for scraping operations
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
- **BeautifulSoup4**: HTML parsing library for extracting listing data
- **Requests**: HTTP client for making web requests to Marktplaats
- **lxml**: Fast XML/HTML parser for BeautifulSoup
- **Pydantic**: Data validation for API request/response models

## API Endpoints
- **GET /scrape**: Single search with pagination support
- **POST /batch-search**: Multiple searches for Pinterest board matching  
- **GET /health**: Health check endpoint
- **GET /**: API documentation and endpoint overview

## Integration Features
- **Pinterest Board Matching**: Designed to process multiple search terms from Pinterest boards
- **Structured Data Output**: Returns consistent JSON format for easy frontend integration
- **Error Handling**: Graceful handling of network issues and parsing errors
- **Logging**: Comprehensive logging for debugging and monitoring