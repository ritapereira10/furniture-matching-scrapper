"""
Pinterest Image Ingestion Module for Atelier

Extracts images from Pinterest board URLs for style analysis.
Uses requests-based extraction (no browser automation required).
"""

import re
import json
import hashlib
import logging
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

PINTEREST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_image_cache: dict[str, list[bytes]] = {}


def _get_cache_key(url: str) -> str:
    """Generate cache key from URL."""
    return hashlib.md5(url.encode()).hexdigest()


def _extract_board_id(url: str) -> Optional[str]:
    """Extract board identifier from Pinterest URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        return path
    return None


def _extract_images_from_html(html: str) -> list[str]:
    """Extract image URLs from Pinterest HTML using regex patterns."""
    image_urls = []
    
    patterns = [
        r'"url"\s*:\s*"(https://i\.pinimg\.com/[^"]+)"',
        r'src="(https://i\.pinimg\.com/[^"]+)"',
        r'"imageSpec"[^}]*"url"\s*:\s*"(https://[^"]+pinimg[^"]+)"',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for match in matches:
            if "236x" in match or "474x" in match or "564x" in match or "736x" in match:
                clean_url = match.replace("\\/", "/")
                if clean_url not in image_urls:
                    image_urls.append(clean_url)
    
    preferred = [u for u in image_urls if "564x" in u or "736x" in u]
    if len(preferred) >= 5:
        return preferred
    
    return image_urls


def _download_image(url: str, timeout: int = 10) -> Optional[bytes]:
    """Download a single image."""
    try:
        resp = requests.get(url, headers=PINTEREST_HEADERS, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except Exception as e:
        logger.debug(f"Failed to download {url}: {e}")
    return None


def get_pinterest_images(board_url: str, max_images: int = 10, use_cache: bool = True) -> list[bytes]:
    """
    Extract images from a Pinterest board URL.
    
    Args:
        board_url: Pinterest board URL
        max_images: Maximum number of images to return (default 10)
        use_cache: Whether to use cached results (default True)
    
    Returns:
        List of image bytes
    """
    cache_key = _get_cache_key(board_url)
    
    if use_cache and cache_key in _image_cache:
        logger.info(f"Using cached images for {board_url}")
        return _image_cache[cache_key][:max_images]
    
    logger.info(f"Fetching Pinterest board: {board_url}")
    
    try:
        resp = requests.get(board_url, headers=PINTEREST_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Pinterest returned status {resp.status_code}")
            return []
        
        html = resp.text
        image_urls = _extract_images_from_html(html)
        logger.info(f"Found {len(image_urls)} image URLs")
        
        if not image_urls:
            logger.warning("No images found in Pinterest HTML")
            return []
        
        images = []
        for url in image_urls[:max_images * 2]:
            if len(images) >= max_images:
                break
            img_bytes = _download_image(url)
            if img_bytes:
                images.append(img_bytes)
        
        logger.info(f"Downloaded {len(images)} images from Pinterest")
        
        if use_cache and images:
            _image_cache[cache_key] = images
        
        return images[:max_images]
        
    except Exception as e:
        logger.error(f"Pinterest scraping failed: {e}")
        return []


def extract_style_hints_from_url(board_url: str) -> dict:
    """
    Extract style hints from Pinterest URL path (fallback when images unavailable).
    
    Args:
        board_url: Pinterest board URL
    
    Returns:
        Dict with possible style hints extracted from URL
    """
    url_lower = board_url.lower()
    
    hints = {
        "styles": [],
        "materials": [],
        "objects": [],
        "room_types": []
    }
    
    style_keywords = {
        "mid-century": ["mid-century", "midcentury", "mid century", "mcm", "60s", "50s"],
        "scandinavian": ["scandinavian", "scandi", "nordic", "danish", "swedish"],
        "industrial": ["industrial", "loft", "factory"],
        "minimalist": ["minimal", "minimalist", "clean"],
        "boho": ["boho", "bohemian", "eclectic"],
        "vintage": ["vintage", "retro", "antique"],
        "modern": ["modern", "contemporary"],
        "rustic": ["rustic", "farmhouse", "cottage"]
    }
    
    material_keywords = {
        "teak": ["teak"],
        "oak": ["oak", "eiken"],
        "walnut": ["walnut", "walnoot"],
        "wood": ["wood", "wooden", "hout"],
        "metal": ["metal", "iron", "steel"],
        "leather": ["leather", "leer"]
    }
    
    object_keywords = {
        "desk": ["desk", "bureau", "workspace", "office"],
        "chair": ["chair", "stoel", "seating"],
        "table": ["table", "tafel", "dining"],
        "sofa": ["sofa", "couch", "bank"],
        "cabinet": ["cabinet", "kast", "storage"],
        "lamp": ["lamp", "lighting", "light"]
    }
    
    room_keywords = {
        "living": ["living", "woonkamer", "lounge"],
        "dining": ["dining", "eetkamer"],
        "bedroom": ["bedroom", "slaapkamer"],
        "office": ["office", "workspace", "study"]
    }
    
    for style, keywords in style_keywords.items():
        if any(kw in url_lower for kw in keywords):
            hints["styles"].append(style)
    
    for material, keywords in material_keywords.items():
        if any(kw in url_lower for kw in keywords):
            hints["materials"].append(material)
    
    for obj, keywords in object_keywords.items():
        if any(kw in url_lower for kw in keywords):
            hints["objects"].append(obj)
    
    for room, keywords in room_keywords.items():
        if any(kw in url_lower for kw in keywords):
            hints["room_types"].append(room)
    
    return hints


def clear_cache():
    """Clear the image cache."""
    global _image_cache
    _image_cache = {}
    logger.info("Pinterest image cache cleared")
