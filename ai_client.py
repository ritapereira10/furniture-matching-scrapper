"""
AI Client Module for Atelier
Provides three core AI functions:
1. extract_style(images) - Vision API for Pinterest image analysis
2. embed(items) - TF-IDF vectorization for semantic similarity
3. explain_match(style, listing) - LLM explanations for matches

Uses Replit AI Integrations for OpenAI access (no API key required, billed to credits).
Uses scikit-learn TF-IDF for local embeddings (free, no API calls).
"""

import os
import re
import json
import base64
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from openai import OpenAI

logger = logging.getLogger(__name__)

AI_INTEGRATIONS_OPENAI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

openai_client = None
if AI_INTEGRATIONS_OPENAI_API_KEY and AI_INTEGRATIONS_OPENAI_BASE_URL:
    openai_client = OpenAI(
        api_key=AI_INTEGRATIONS_OPENAI_API_KEY,
        base_url=AI_INTEGRATIONS_OPENAI_BASE_URL
    )

STYLE_EXTRACTION_SCHEMA = {
    "styles": ["mid-century modern", "scandinavian", "industrial", "minimalist", "boho", "modern", "rustic", "art deco", "vintage"],
    "materials": ["oak", "teak", "walnut", "wood", "metal", "leather", "linen", "velvet", "rattan", "marble", "glass"],
    "colors": ["warm wood", "cream", "black", "white", "natural", "earth tones", "muted", "bold"],
    "objects": ["dining table", "desk", "chair", "sofa", "cabinet", "shelf", "lamp", "bed", "dresser"],
    "vibe_keywords": ["minimal", "warm", "clean lines", "cozy", "airy", "bold", "eclectic", "refined"],
    "avoid": ["high gloss", "ornate", "cheap", "plastic", "mass-produced"]
}


def is_rate_limit_error(exception: BaseException) -> bool:
    """Check if the exception is a rate limit error."""
    error_msg = str(exception)
    return (
        "429" in error_msg
        or "RATELIMIT_EXCEEDED" in error_msg
        or "quota" in error_msg.lower()
        or "rate limit" in error_msg.lower()
        or (hasattr(exception, "status_code") and getattr(exception, "status_code", None) == 429)
    )


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(is_rate_limit_error),
    reraise=True
)
def extract_style(images: list[bytes], max_images: int = 8) -> dict:
    """
    Extract style profile from Pinterest images using vision AI.
    
    Args:
        images: List of image bytes from Pinterest board
        max_images: Maximum number of images to analyze (default 8)
    
    Returns:
        Style profile dict with keys: styles, materials, colors, objects, vibe_keywords, avoid
    """
    if not openai_client:
        logger.warning("OpenAI client not configured, using fallback extraction")
        return _fallback_style_profile()
    
    if not images:
        logger.warning("No images provided for style extraction")
        return _fallback_style_profile()
    
    images_to_analyze = images[:max_images]
    
    text_content = """Analyze these Pinterest board images to extract the furniture aesthetic and style preferences.

Return ONLY valid JSON with this exact structure:
{
    "styles": ["list of style names like: mid-century modern, scandinavian, industrial, minimalist, boho, modern, rustic"],
    "materials": ["list of materials like: oak, teak, walnut, wood, metal, leather, linen, rattan"],
    "colors": ["list of color descriptions like: warm wood, cream, black accents, earth tones"],
    "objects": ["list of furniture types shown like: dining table, desk, chair, sofa, cabinet"],
    "vibe_keywords": ["descriptive words like: minimal, warm, clean lines, cozy, refined"],
    "avoid": ["things NOT in this aesthetic like: high gloss, ornate, plastic"],
    "confidence": 0.85
}

Be specific and accurate. Only include styles/materials you actually see in the images."""

    content: list = [{"type": "text", "text": text_content}]
    
    for img_bytes in images_to_analyze:
        b64_image = base64.b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64_image}",
                "detail": "low"
            }
        })
    
    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],  # type: ignore
            response_format={"type": "json_object"},
            max_tokens=1024
        )
        
        result_text = response.choices[0].message.content or "{}"
        style_profile = json.loads(result_text)
        
        for key in ["styles", "materials", "colors", "objects", "vibe_keywords", "avoid"]:
            if key not in style_profile:
                style_profile[key] = []
        
        if "confidence" not in style_profile:
            style_profile["confidence"] = 0.7
        
        logger.info(f"Extracted style profile: {json.dumps(style_profile, indent=2)}")
        return style_profile
        
    except Exception as e:
        logger.error(f"Style extraction failed: {e}")
        return _fallback_style_profile()


def _fallback_style_profile() -> dict:
    """Return a generic fallback style profile."""
    return {
        "styles": ["vintage", "design"],
        "materials": ["wood"],
        "colors": ["natural"],
        "objects": ["furniture"],
        "vibe_keywords": ["classic"],
        "avoid": [],
        "confidence": 0.3
    }


def compute_similarity_scores(query_text: str, listing_texts: list[str], top_k: int = 20) -> list[tuple[int, float]]:
    """
    Compute similarity between query and listings using TF-IDF.
    Creates a fresh vectorizer per call to avoid global state issues.
    
    Args:
        query_text: The style profile as text
        listing_texts: List of listing texts (title + description)
        top_k: Number of top results to return
    
    Returns:
        List of (index, score) tuples sorted by similarity
    """
    if not listing_texts:
        return []
    
    vectorizer = TfidfVectorizer(
        max_features=500,
        ngram_range=(1, 2),
        stop_words=None,
        lowercase=True
    )
    
    all_texts = listing_texts + [query_text]
    vectors = vectorizer.fit_transform(all_texts)
    
    query_vec = vectors[-1]
    listing_vecs = vectors[:-1]
    
    similarities = cosine_similarity(query_vec, listing_vecs)[0]
    
    indices = np.argsort(similarities)[::-1][:top_k]
    return [(int(idx), float(similarities[idx])) for idx in indices]


def embed(items: list[str]) -> np.ndarray:
    """
    Embed listing texts into vectors for similarity search.
    Creates fresh vectorizer per call.
    
    Args:
        items: List of listing texts (title + description)
    
    Returns:
        Numpy array of embeddings
    """
    if not items:
        return np.array([])
    
    vectorizer = TfidfVectorizer(
        max_features=500,
        ngram_range=(1, 2),
        stop_words=None,
        lowercase=True
    )
    vectors = vectorizer.fit_transform(items)
    return vectors.toarray()


def retrieve_candidates(style_profile: dict, listings: list[dict], top_k: int = 20) -> list[dict]:
    """
    Retrieve top-k candidates using TF-IDF similarity.
    Uses request-scoped vectorizer to avoid global state issues.
    Falls back to deterministic ordering when style profile is empty.
    
    Args:
        style_profile: Style profile from extract_style()
        listings: List of listing dicts with 'title' and 'description'
        top_k: Number of candidates to return
    
    Returns:
        List of listings sorted by relevance, with 'similarity_score' added
    """
    if not listings:
        return []
    
    style_parts = [
        " ".join(style_profile.get("styles", [])),
        " ".join(style_profile.get("materials", [])),
        " ".join(style_profile.get("colors", [])),
        " ".join(style_profile.get("objects", [])),
        " ".join(style_profile.get("vibe_keywords", []))
    ]
    style_text = " ".join(style_parts).strip()
    
    if not style_text or len(style_text.split()) < 2:
        style_text = "vintage design furniture wood"
        logger.info("Empty style profile, using fallback query terms")
    
    listing_texts = [
        f"{l.get('title', '')} {l.get('description', '')}"
        for l in listings
    ]
    
    if not listing_texts:
        return listings[:top_k]
    
    try:
        top_indices = compute_similarity_scores(style_text, listing_texts, top_k=top_k)
        
        if not top_indices:
            return listings[:top_k]
        
        results = []
        for idx, score in top_indices:
            if idx < len(listings):
                listing = listings[idx].copy()
                listing["similarity_score"] = score
                results.append(listing)
        
        return results if results else listings[:top_k]
        
    except Exception as e:
        logger.warning(f"Similarity scoring failed: {e}, returning original listings")
        return listings[:top_k]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(is_rate_limit_error),
    reraise=True
)
def explain_match(style_profile: dict, listing: dict) -> dict:
    """
    Generate explanation for why a listing matches the style profile.
    
    Args:
        style_profile: Style profile from extract_style()
        listing: Single listing dict
    
    Returns:
        Explanation dict with 'why_matches', 'tradeoff', 'matched_attributes'
    """
    if not openai_client:
        return _fallback_explanation(listing)
    
    prompt = f"""You are a furniture curator. Explain why this listing matches the user's style preferences.

USER STYLE PREFERENCES:
- Styles: {', '.join(style_profile.get('styles', []))}
- Materials: {', '.join(style_profile.get('materials', []))}
- Colors: {', '.join(style_profile.get('colors', []))}
- Vibes: {', '.join(style_profile.get('vibe_keywords', []))}
- Avoid: {', '.join(style_profile.get('avoid', []))}

LISTING:
Title: {listing.get('title', 'Unknown')}
Description: {listing.get('description', 'No description')}
Price: {listing.get('price', 'Unknown')}

Return ONLY valid JSON:
{{
    "why_matches": "One sentence explaining the match",
    "tradeoff": "One sentence about any uncertainty or tradeoff",
    "matched_attributes": ["list", "of", "3", "matched", "attributes"]
}}"""

    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=256
        )
        
        result = json.loads(response.choices[0].message.content or "{}")
        return {
            "why_matches": result.get("why_matches", "This piece matches your aesthetic preferences."),
            "tradeoff": result.get("tradeoff", "Verify condition and dimensions in person."),
            "matched_attributes": result.get("matched_attributes", [])[:3]
        }
        
    except Exception as e:
        logger.error(f"Explanation generation failed: {e}")
        return _fallback_explanation(listing)


def _fallback_explanation(listing: dict) -> dict:
    """Generate a simple fallback explanation."""
    return {
        "why_matches": f"'{listing.get('title', 'This piece')}' fits your curated collection.",
        "tradeoff": "Check the original listing for full details.",
        "matched_attributes": ["design", "style", "character"]
    }


def explain_matches(style_profile: dict, listings: list[dict], max_concurrent: int = 3) -> list[dict]:
    """
    Generate explanations for multiple listings concurrently.
    
    Args:
        style_profile: Style profile from extract_style()
        listings: List of listings to explain
        max_concurrent: Max concurrent API calls
    
    Returns:
        List of listings with 'explanation' field added
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_idx = {
            executor.submit(explain_match, style_profile, listing): i
            for i, listing in enumerate(listings)
        }
        
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                explanation = future.result()
                listing = listings[idx].copy()
                listing["explanation"] = explanation
                results.append((idx, listing))
            except Exception as e:
                logger.error(f"Failed to explain listing {idx}: {e}")
                listing = listings[idx].copy()
                listing["explanation"] = _fallback_explanation(listing)
                results.append((idx, listing))
    
    results.sort(key=lambda x: x[0])
    return [r[1] for r in results]


def style_profile_to_queries(style_profile: dict) -> list[str]:
    """
    Convert style profile to Dutch Marktplaats search queries.
    
    Args:
        style_profile: Style profile from extract_style()
    
    Returns:
        List of Dutch search query strings
    """
    style_to_dutch = {
        "mid-century modern": "jaren 60",
        "mid-century": "jaren 60",
        "scandinavian": "scandinavisch",
        "industrial": "industrieel",
        "minimalist": "minimalistisch",
        "boho": "bohemian",
        "modern": "modern design",
        "rustic": "landelijk",
        "vintage": "vintage",
        "art deco": "art deco"
    }
    
    material_to_dutch = {
        "oak": "eiken",
        "teak": "teak",
        "walnut": "notenhout",
        "wood": "houten",
        "metal": "metaal",
        "leather": "leren",
        "rattan": "rotan",
        "marble": "marmer",
        "glass": "glas"
    }
    
    object_to_dutch = {
        "dining table": "eettafel",
        "desk": "bureau",
        "chair": "stoel",
        "sofa": "bank",
        "cabinet": "kast",
        "shelf": "boekenkast",
        "lamp": "lamp",
        "bed": "bed",
        "dresser": "dressoir",
        "coffee table": "salontafel"
    }
    
    queries = []
    
    dutch_styles = []
    for style in style_profile.get("styles", []):
        style_lower = style.lower()
        if style_lower in style_to_dutch:
            dutch_styles.append(style_to_dutch[style_lower])
    
    dutch_materials = []
    for material in style_profile.get("materials", []):
        material_lower = material.lower()
        if material_lower in material_to_dutch:
            dutch_materials.append(material_to_dutch[material_lower])
    
    dutch_objects = []
    for obj in style_profile.get("objects", []):
        obj_lower = obj.lower()
        if obj_lower in object_to_dutch:
            dutch_objects.append(object_to_dutch[obj_lower])
    
    if not dutch_objects:
        dutch_objects = ["meubels", "bureau", "stoel"]
    
    for obj in dutch_objects[:3]:
        if dutch_styles:
            queries.append(f"{obj} {dutch_styles[0]}")
        if dutch_materials:
            queries.append(f"{obj} {dutch_materials[0]}")
        if not dutch_styles and not dutch_materials:
            queries.append(f"{obj} design")
    
    unique_queries = list(dict.fromkeys(queries))
    logger.info(f"Generated queries from style profile: {unique_queries}")
    return unique_queries[:6]


def refine_style(
    style_profile: dict,
    constraints: dict,
    user_message: str
) -> tuple[dict, dict]:
    """
    Refine style profile and constraints based on user feedback.
    Falls back to keyword-based parsing if OpenAI unavailable.
    
    Args:
        style_profile: Current style profile
        constraints: Current constraints (price_max, city, etc.)
        user_message: User's refinement request
    
    Returns:
        Tuple of (updated_style_profile, updated_constraints)
    """
    user_lower = user_message.lower()
    updated_constraints = constraints.copy() if constraints else {}
    updated_style = style_profile.copy() if style_profile else {}
    
    price_match = re.search(r'under\s*€?\s*(\d+)|max\s*€?\s*(\d+)|€\s*(\d+)', user_lower)
    if price_match:
        price = price_match.group(1) or price_match.group(2) or price_match.group(3)
        updated_constraints["price_max"] = int(price)
    
    city_keywords = ["amsterdam", "rotterdam", "utrecht", "den haag", "eindhoven", "groningen"]
    for city in city_keywords:
        if city in user_lower:
            updated_constraints["city"] = city.replace(" ", "-")
            break
    
    if not openai_client:
        logger.warning("OpenAI client not configured, using keyword-based refinement")
        return updated_style, updated_constraints
    
    prompt = f"""Parse this user refinement request and update the style profile and constraints.

CURRENT STYLE PROFILE:
{json.dumps(style_profile, indent=2)}

CURRENT CONSTRAINTS:
{json.dumps(constraints, indent=2)}

USER REQUEST: "{user_message}"

Return ONLY valid JSON with two keys:
{{
    "style_profile": {{ updated style profile, keep existing values unless explicitly changed }},
    "constraints": {{ updated constraints like price_max, city, etc. }}
}}

Constraint changes should be prioritized over style changes. Only modify what the user explicitly requests."""

    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=512
        )
        
        result = json.loads(response.choices[0].message.content or "{}")
        updated_style = result.get("style_profile", style_profile)
        updated_constraints = result.get("constraints", constraints)
        
        return updated_style, updated_constraints
        
    except Exception as e:
        logger.error(f"Refinement failed: {e}")
        return updated_style, updated_constraints


def translate_title(title: str, target_language: str = "en") -> str:
    """
    Translate a title from Dutch to the target language.
    
    Args:
        title: The title to translate (likely in Dutch)
        target_language: Target language code (en, nl, pt, de, fr)
    
    Returns:
        Translated title, or original if translation fails
    """
    if target_language == "nl":
        return title
    
    if not openai_client:
        return title
    
    lang_names = {
        "en": "English",
        "pt": "Portuguese",
        "de": "German",
        "fr": "French"
    }
    
    target_lang_name = lang_names.get(target_language, "English")
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Translate this Dutch furniture listing title to {target_lang_name}. Only return the translated title, nothing else.\n\nTitle: {title}"
            }],
            max_tokens=100
        )
        
        translated = response.choices[0].message.content.strip()
        return translated if translated else title
        
    except Exception as e:
        logger.warning(f"Translation failed for '{title}': {e}")
        return title


def translate_titles_batch(titles: list[str], target_language: str = "en") -> list[str]:
    """
    Translate multiple titles from Dutch to target language in batch.
    
    Args:
        titles: List of titles to translate
        target_language: Target language code
    
    Returns:
        List of translated titles
    """
    if target_language == "nl" or not titles:
        return titles
    
    if not openai_client:
        return titles
    
    lang_names = {
        "en": "English",
        "pt": "Portuguese", 
        "de": "German",
        "fr": "French"
    }
    
    target_lang_name = lang_names.get(target_language, "English")
    numbered_titles = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"""Translate these Dutch furniture listing titles to {target_lang_name}. 
Return ONLY the translated titles, one per line, keeping the same numbering format.

{numbered_titles}"""
            }],
            max_tokens=500
        )
        
        result = response.choices[0].message.content.strip()
        translated_lines = result.split("\n")
        
        translated = []
        for line in translated_lines:
            clean = re.sub(r'^\d+\.\s*', '', line.strip())
            if clean:
                translated.append(clean)
        
        if len(translated) == len(titles):
            return translated
        else:
            return titles
        
    except Exception as e:
        logger.warning(f"Batch translation failed: {e}")
        return titles
