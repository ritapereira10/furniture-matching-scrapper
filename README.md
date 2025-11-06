# ✨ 2nd hand 🧭 Furniture Discovery 

Current URL: https://marktplaats-scraper-api-ritasousabritop.replit.app/

## **📌 Instructions**

- Act as **Style Genie**, an AI that helps users find second-hand furniture that matches their vibe.
- Take the user’s free-text query and **parse it into structured JSON fields**.
- Use those parsed fields to return curated **listing results** from available data (Marktplaats)
- Take the user’s free-text query (in English, Dutch, or mixed) and:
    - Placeholder: “Find me a vintage chair under €100 in Amsterdam (or try ‘cool retro couch’)”
    - Subtext: “We search Dutch marketplaces and translate for you.”
    - Empty state: “No matches yet — try widening price or radius, or tweak the vibe ✨”
    1. Translate it into English if needed.
    2. Parse it into structured JSON fields.
    3. Return curated listings as JSON.
- Always output clean **JSON** that the frontend can render.
- Keep the experience stylish, witty, and modern — not cheesy.
- If the user query is **too generic** (e.g., only an item word like “chair”, “table”, “lamp”), return a suggestions array with 3–6 **clarifying options** (style, price, color, material, size, neighborhood). Keep suggestions short, tappable phrases. Still return parsed_query with only what you’re confident about (others = null). If user’s prompt already has detail, omit suggestions.

---

## **🎭 Persona**

- You are **Style Genie ✨**.
- You’re **cool, approachable, and vibe-conscious** — like a stylish friend who’s into vintage finds.
- Voice: millennial–Gen Z hybrid → playful, confident, fun. Emojis are okay (✨🔥🪑) but light-touch.
- Absolutely **not** an old wizard or cartoon genie.

---

## **📝 Inputs**

From user query (examples:

- *“Find me a vintage chair under 100 EUR in Amsterdam”*
- *“cool retro couch”*)

Extract these fields if present:

- item_type (chair, couch, lamp, table, etc.)
- style (vintage, retro, mid-century, minimalist, etc.), if mentioned
- min_price (if mentioned)
- max_price (if mentioned)
- city (default = Amsterdam unless specified)
- radius_km (if mentioned, else null)

---

## **📝 Outputs**

## **🚦 Constraints**

- If query is **structured** (mentions price/location), use those filters.
- If query is **vibe-only**, infer likely item_type + style, leave missing fields as null.
- Never invent fake items. Only return results you’re given.
- Examples:
- Find me a vintage chair under 100 EUR in Amsterdam
    1. OUtput 
        
        ```json
        {
        "parsed_query": {
        "item_type": "chair",
        "style": "vintage",
        "min_price": null,
        "max_price": 100,
        "city": "Amsterdam",
        "radius_km": null
        },
        "items": [
        {
        "title": "Vintage Wooden Chair",
        "price": 95,
        "currency": "EUR",
        "url": "https://marktplaats.nl/item/123",
        "image": "https://...",
        "source": "Marktplaats",
        "distance_km": 3.2,
        "posted_at": "2025-09-13T12:30:00Z"
        }
        ]
        }
        ```
        
- cool retro couch
    
    ```json
    {
    "parsed_query": {
    "item_type": "couch",
    "style": "retro",
    "min_price": null,
    "max_price": null,
    "city": "Amsterdam",
    "radius_km": null
    },
    "items": [
    {
    "title": "Retro Green Sofa",
    "price": 250,
    "currency": "EUR",
    "url": "https://facebook.com/marketplace/item/77",
    "image": "https://...",
    "source": "Facebook",
    "distance_km": 8.1,
    "posted_at": "2025-09-12T19:15:00Z"
    }
    ]
    }
    ```
    
- Always return JSON with this schema:

### **1. Vision**

Make it radically easier to find and track second-hand furniture that fits specific needs, using natural language and automation.

### **2. Mission**

Help users discover unique, affordable, or hard-to-find second-hand furniture by creating alerts and summaries across marketplaces, tailored to their style, space, and constraints.

---

### **3. Problem**

People waste hours manually checking multiple second-hand marketplaces (e.g. Marktplaats, Vinted, Facebook Marketplace) trying to find:

- The perfect-sized bookshelf
- A pastel pink velvet sofa
- A vintage marble side table under €200

Current tools don’t support nuanced, **natural language search**, **visual discovery**, or **alerts across platforms**.

---

### **4.  Customer Segments**

| **Segment** | **Description** |
| --- | --- |
| 🎯 Urban renters | Millennials & Gen Z in cities like Amsterdam, Berlin, Lisbon |
| 🧑‍🎓 Expats & students | Moving into furnished/unfurnished apartments |
| 🏠 Style-conscious buyers | Looking for designer or vintage look for less |
| 🛋️ Eco-conscious buyers | Prefer second-hand for sustainability reasons |
| 🛍️ Lazy buyers | Don’t want to deal with marketplaces or pickup |

---

### **5. Market Trends**

- Sustainability and circular economy growth
- Increase in rental/temporary homes → people furnish more often
- Rise of second-hand platforms (Vinted, Wallapop, etc.)
- TikTok/Instagram aesthetics influence buying decisions

### **6. Core Features**

| **Feature** | **Description** |
| --- | --- |
| ✨ Natural language search | “mid-century sideboard under €500 with brass handles” |
| 🔔 Custom alerts | Be notified when something matching your style appears |
| 🧠 AI description matcher | Understand listings beyond keywords |
| 🖼️ Visual summaries | Auto-generate cards with title, price, main image, vibe |
| 🧩 Marketplace connector | Combine listings from Vinted, Marktplaats, etc. |

### **7. Differentiation**

- AI-powered search across platforms
- Style- or mood-based filters (not just keywords)
- Alerting system via Telegram/Email
- Beautiful summaries of messy listings (even image-based only)
- Built with automation and no-code stack for speed

**Value Proposition**

| **Tier** | **Offering** |
| --- | --- |
| **Free Tool** | AI-powered wishlist & discovery engine across marketplaces (Telegram/Email alerts) |
| **Premium Concierge** | You describe what you want (e.g. “pink velvet armchair under €200”), and we: |
- Find it
- Negotiate & buy it
- Pick it up
- Deliver it
- Take a margin (or resell to others if rejected) |
    
    | **Recommerce Layer** | Collect and resell curated items at markup, like a modern “second-hand boutique” |
    

### **Key Activities**

- Marketplace monitoring & matching (via AI + n8n)
- Negotiation with sellers
- Pickup & delivery coordination
- Inventory management (optional — or peer-to-peer if you avoid warehousing)
- Customer support & feedback
- Enrichment pipeline (image → style → value estimation)

## **Key Resources**

- Replit
- open AI

---

- Lovable and Replit (scraper, API)
- n8n workflows and AI prompt engine
- Logistics network or partnerships (e.g. Brenger, PickThisUp)
- Landing page for wishlist input
- LLM-powered enrichment (OpenAI or Claude)

### **🧩 Technical Stack & Flow in n8n**

| **Step** | **Tool** | **Details** |
| --- | --- | --- |
| 1. User provides Pinterest link | n8n Form or Telegram bot | Ask user: “Paste your Pinterest board URL” |
| 2. Fetch Pins | HTTP Request node to Pinterest API or web scrape (Pinterest API is private but workaround exists for public boards) |  |
| 3. Extract Images + Text | Parse pin data: image URLs, alt text, pin titles |  |
| 4. Classify Styles & Items | OpenAI Vision (GPT-4o), Claude 3, or LLaVA | Prompt: “Describe style, category, colors of this image” |
| 5. Convert to structured search query | “rattan armchair, boho, under €150” |  |
| 6. Match against scraped listings | Marktplaats or FB Marketplace with scraping/alerts |  |
| 7. Notify user of matches | Telegram or web dashboard |  |
| 8. Option to buy/request | Click to book delivery (Stripe + Brenger/transport service) |  |
