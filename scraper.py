import requests
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urljoin, quote
from typing import List, Dict, Optional
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MarktplaatsScraper:
    def __init__(self):
        self.base_url = "https://www.marktplaats.nl"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text.strip())
    
    def _extract_price(self, price_text: str) -> Dict[str, Optional[str]]:
        """Extract and normalize price information"""
        if not price_text:
            return {"price": None, "price_type": "unknown"}
            
        price_text = self._clean_text(price_text.lower())
        
        if "bieden" in price_text or "op aanvraag" in price_text:
            return {"price": None, "price_type": "negotiable"}
        
        # Extract euro amounts
        euro_match = re.search(r'€\s*([0-9.,]+)', price_text)
        if euro_match:
            price_value = euro_match.group(1).replace('.', '').replace(',', '.')
            try:
                float_price = float(price_value)
                return {"price": f"€{float_price:.2f}", "price_type": "fixed"}
            except ValueError:
                return {"price": euro_match.group(0), "price_type": "fixed"}
        
        return {"price": price_text, "price_type": "unknown"}
    
    def _extract_location(self, location_text: str) -> str:
        """Extract location information"""
        if not location_text:
            return ""
        
        # Remove common prefixes like "Ophalen" or "Verzenden"
        cleaned = re.sub(r'^(ophalen|verzenden|vanaf|in)\s*', '', location_text.lower(), flags=re.IGNORECASE)
        return self._clean_text(cleaned).title()
    
    def search(self, query: str, max_results: int = 50, category: Optional[str] = None) -> List[Dict]:
        """
        Search for listings on Marktplaats
        
        Args:
            query: Search term
            max_results: Maximum number of results to return
            category: Optional category filter
            
        Returns:
            List of listing dictionaries
        """
        try:
            logger.info(f"Searching for: {query}")
            
            # Build search URL
            search_url = f"{self.base_url}/lrp/api/search"
            
            params = {
                'query': query,
                'searchInTitleAndDescription': 'true',
                'offset': 0,
                'limit': min(max_results, 30),  # Marktplaats typically limits to 30 per page
                'sortBy': 'SortIndex',
                'sortOrder': 'decreasing'
            }
            
            if category:
                params['categoryId'] = category
            
            # Make request with rate limiting
            time.sleep(1)  # Be respectful with requests
            response = self.session.get(search_url, params=params, timeout=30)
            response.raise_for_status()
            
            if response.headers.get('content-type', '').startswith('application/json'):
                # Try API response first
                return self._parse_api_response(response.json())
            else:
                # Fallback to HTML scraping
                return self._scrape_search_page(query, max_results)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            # Fallback to HTML scraping
            return self._scrape_search_page(query, max_results)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def _parse_api_response(self, data: dict) -> List[Dict]:
        """Parse API JSON response"""
        listings = []
        
        # Check for search results in API response
        if 'listings' in data:
            results = data['listings']
        elif '_embedded' in data and 'mp:search-result' in data['_embedded']:
            results = data['_embedded']['mp:search-result']
        else:
            return listings
            
        for item in results:
            try:
                listing = {
                    'title': item.get('title', ''),
                    'price': item.get('priceInfo', {}).get('priceCents', 0) / 100 if item.get('priceInfo', {}).get('priceCents') else None,
                    'price_text': item.get('priceInfo', {}).get('priceType', ''),
                    'location': item.get('location', {}).get('cityName', ''),
                    'description': item.get('description', ''),
                    'link': item.get('vipUrl', ''),
                    'date': item.get('date', ''),
                    'seller_name': item.get('sellerInformation', {}).get('sellerName', ''),
                    'image_url': item.get('pictures', [{}])[0].get('extraExtraLargeUrl', '') if item.get('pictures') else ''
                }
                
                # Ensure full URL
                if listing['link'] and not listing['link'].startswith('http'):
                    listing['link'] = urljoin(self.base_url, listing['link'])
                
                listings.append(listing)
                
            except Exception as e:
                logger.warning(f"Failed to parse listing: {e}")
                continue
                
        return listings
    
    def _scrape_search_page(self, query: str, max_results: int) -> List[Dict]:
        """Fallback HTML scraping method"""
        try:
            # Build search URL for HTML version
            search_url = f"{self.base_url}/s/{quote(query)}"
            
            logger.info(f"Scraping HTML from: {search_url}")
            
            response = self.session.get(search_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            listings = []
            
            # Look for listing containers (these selectors may need adjustment)
            listing_selectors = [
                '.mp-listing',
                '.hz-Listing',
                '[data-testid*="listing"]',
                '.mp-listing-item',
                'article[class*="listing"]'
            ]
            
            listing_elements = []
            for selector in listing_selectors:
                elements = soup.select(selector)
                if elements:
                    listing_elements = elements
                    logger.info(f"Found {len(elements)} listings using selector: {selector}")
                    break
            
            for element in listing_elements[:max_results]:
                try:
                    listing = self._extract_listing_data(element)
                    if listing and listing.get('title'):
                        listings.append(listing)
                except Exception as e:
                    logger.warning(f"Failed to extract listing: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(listings)} listings")
            return listings
            
        except Exception as e:
            logger.error(f"HTML scraping failed: {e}")
            return []
    
    def _extract_listing_data(self, element) -> Dict:
        """Extract listing data from HTML element"""
        listing = {
            'title': '',
            'price': None,
            'price_text': '',
            'location': '',
            'description': '',
            'link': '',
            'date': '',
            'seller_name': '',
            'image_url': ''
        }
        
        # Extract title
        title_selectors = ['h3', '.mp-listing-title', '[data-testid*="title"]', 'h2', '.hz-Listing-title']
        for selector in title_selectors:
            title_elem = element.select_one(selector)
            if title_elem:
                listing['title'] = self._clean_text(title_elem.get_text())
                break
        
        # Extract price
        price_selectors = ['.mp-listing-price', '[data-testid*="price"]', '.hz-Listing-price', '.price']
        for selector in price_selectors:
            price_elem = element.select_one(selector)
            if price_elem:
                price_info = self._extract_price(price_elem.get_text())
                listing['price'] = price_info['price']
                listing['price_text'] = price_elem.get_text().strip()
                break
        
        # Extract location
        location_selectors = ['.mp-listing-location', '[data-testid*="location"]', '.hz-Listing-location', '.location']
        for selector in location_selectors:
            location_elem = element.select_one(selector)
            if location_elem:
                listing['location'] = self._extract_location(location_elem.get_text())
                break
        
        # Extract description
        desc_selectors = ['.mp-listing-description', '[data-testid*="description"]', '.hz-Listing-description', '.description']
        for selector in desc_selectors:
            desc_elem = element.select_one(selector)
            if desc_elem:
                listing['description'] = self._clean_text(desc_elem.get_text())
                break
        
        # Extract link
        link_elem = element.select_one('a[href]')
        if link_elem:
            href = link_elem.get('href')
            if href:
                listing['link'] = urljoin(self.base_url, href) if not href.startswith('http') else href
        
        # Extract image
        img_elem = element.select_one('img[src], img[data-src]')
        if img_elem:
            img_src = img_elem.get('src') or img_elem.get('data-src')
            if img_src:
                listing['image_url'] = urljoin(self.base_url, img_src) if not img_src.startswith('http') else img_src
        
        return listing

# Utility function for testing
def test_scraper():
    """Test function to verify scraper works"""
    scraper = MarktplaatsScraper()
    results = scraper.search("laptop", max_results=5)
    
    print(f"Found {len(results)} results:")
    for i, listing in enumerate(results, 1):
        print(f"\n{i}. {listing['title']}")
        print(f"   Price: {listing['price'] or listing['price_text']}")
        print(f"   Location: {listing['location']}")
        print(f"   Link: {listing['link']}")

if __name__ == "__main__":
    test_scraper()