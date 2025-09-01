from fastapi import FastAPI
from playwright.sync_api import sync_playwright
import pandas as pd

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Marktplaats Scraper API"}

@app.get("/scrape")
def scrape_marktplaats():
    listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
            locale="nl-NL"
        )
        page = context.new_page()

        # ✅ Adjust the search query & filters as needed
        url = "https://www.marktplaats.nl/l/huis-en-inrichting-tafels-eettafels/?q=rond+houten+tafel&priceTo=150&postcode=1012&distance=20"
        page.goto(url, timeout=30000)

        # Wait for listings to load
        page.wait_for_selector('[data-testid="listing-ad-card"]', timeout=10000)
        cards = page.query_selector_all('[data-testid="listing-ad-card"]')

        for card in cards[:10]:  # Only scrape first 10 results
            title = card.query_selector("h3")
            price = card.query_selector('[data-testid="ad-price"]')
            link = card.query_selector("a")

            listings.append({
                "title": title.inner_text().strip() if title else None,
                "price": price.inner_text().strip() if price else None,
                "link": "https://www.marktplaats.nl" + link.get_attribute("href") if link else None,
            })

        browser.close()

    return listings