from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Marktplaats Scraper API"}

@app.get("/scrape")
def scrape():
    try:
        # TEMP placeholder for testing
        return {"items": ["item1", "item2", "item3"]}
    except Exception as e:
        return {"error": "An error occurred while scraping", "details": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000)