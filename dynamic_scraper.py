#!/usr/bin/env python3
"""
Dynamic Startup Funding Scraper
- Runs forever, checks sources every 6 hours
- Only ingests NEW data (deduplication)
- Logs everything, restarts on error
"""

import requests
import feedparser
import pandas as pd
import fitz
from bs4 import BeautifulSoup
import time
import sqlite3
import hashlib
import json
from datetime import datetime
import logging
from pathlib import Path

# CONFIG
RAG_INGEST_URL = "http://localhost:8000/ingest"
SCRAPE_INTERVAL = 4 * 60   # 4 mins
MAX_CHUNK_SIZE = 2000

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Local dedup DB
DB_PATH = "scraper_dedup.db"

def init_dedup_db():
    """Track already ingested content"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingested (
            hash TEXT PRIMARY KEY,
            source TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_already_ingested(content_hash, source):
    """Check if content exists"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT 1 FROM ingested WHERE hash=?", (content_hash,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def mark_ingested(content_hash, source):
    """Mark as ingested"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO ingested (hash, source) VALUES (?, ?)", 
                (content_hash, source))
    conn.commit()
    conn.close()

def chunk_text(text, max_size=MAX_CHUNK_SIZE):
    """Split long text"""
    return [text[i:i+max_size] for i in range(0, len(text), max_size)]

def ingest_if_new(text, source, doc_type="dynamic", url=None):
    """Ingest only if NEW"""
    content_hash = hashlib.md5(text.encode()).hexdigest()
    
    if is_already_ingested(content_hash, source):
        return False
    
    payload = {
        "text": text,
        "source": source,
        "url": url or f"dynamic_scraper_{int(time.time())}",
        "doc_type": doc_type
    }
    
    try:
        r = requests.post(RAG_INGEST_URL, json=payload, timeout=15)
        if r.status_code == 200:
            mark_ingested(content_hash, source)
            logger.info(f"✅ NEW: {source[:50]}...")
            return True
    except Exception as e:
        logger.error(f"❌ Ingest failed: {e}")
    
    return False


# ============================================================================
# SOURCE 1: RSS FEEDS (Real-time news)
# ============================================================================
def scrape_rss_feeds():
    """Inc42, TechCrunch, Economic Times RSS"""
    rss_feeds = [
        ("Inc42 Latest", "https://inc42.com/feed/"),
        ("TechCrunch India", "https://techcrunch.com/tag/india/feed/"),
        ("Economic Times Startups", "https://economictimes.indiatimes.com/rssfeeds/1066606.cms")
    ]
    
    for name, url in rss_feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:  # Latest 10
                title = entry.title
                summary = entry.summary
                
                if any(keyword in (title + summary).lower() 
                      for keyword in ["funding", "raised", "round", "investor", "cr", "million"]):
                    
                    full_text = f"{title}\n\n{summary}"
                    ingest_if_new(full_text, source=f"RSS-{name}", doc_type="rss_feed", url=url)
                    
            logger.info(f"✅ RSS {name}: checked")
        except Exception as e:
            logger.error(f"❌ RSS {name}: {e}")

# ============================================================================
# SOURCE 2: GROWTHLIST DAILY CHECK
# ============================================================================
def scrape_growthlist():
    """Check for new startups/funding"""
    try:
        url = "https://growthlist.co/india-startups/"
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Recent funding table/sections
        tables = soup.find_all("table")
        cards = soup.find_all("div", class_=re.compile("funding|recent|new", re.I))
        
        for element in tables + cards:
            text = element.get_text()
            if "raised" in text.lower() or "$" in text:
                for chunk in chunk_text(text):
                    ingest_if_new(chunk, "GrowthList Daily", url=url)

        logger.info("✅ GrowthList: checked daily")
    except Exception as e:
        logger.error(f"❌ GrowthList: {e}")

# ============================================================================
# SOURCE 3: INDIAN STARTUP NEWS SITES
# ============================================================================
def scrape_indian_startup_news():
    sites = [
        ("YourStory", "https://yourstory.com"),
        ("IndianStartupNews", "https://indianstartupnews.com"),
        ("Entrackr", "https://entrackr.com"),
        ("StartupIndia", "https://www.startupindia.gov.in/content/sih/en/newsfeed.html")
    ]

    KEYWORDS = [
        "funding", "raised", "round", "seed", "series",
        "venture", "vc", "investment", "capital", "cr", "million"
    ]

    for name, base_url in sites:
        try:
            r = requests.get(base_url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # Extract article links
            links = {
                a["href"] for a in soup.find_all("a", href=True)
                if any(k in a["href"].lower() for k in ["fund", "startup", "invest"])
            }

            for link in list(links)[:10]:  # limit per cycle
                if link.startswith("/"):
                    link = base_url.rstrip("/") + link

                try:
                    ar = requests.get(link, timeout=15)
                    article = BeautifulSoup(ar.text, "html.parser")

                    text = article.get_text(separator=" ", strip=True)
                    text_lower = text.lower()

                    if not any(k in text_lower for k in KEYWORDS):
                        continue

                    # Keep text size sane
                    text = text[:4000]

                    ingest_if_new(
                        text=text,
                        source=name,
                        doc_type="news",
                        url=link
                    )


                except Exception:
                    continue

            logger.info(f"✅ {name}: checked")

        except Exception as e:
            logger.error(f"❌ {name}: {e}")


# ============================================================================
# SOURCE 4: KAGGLE DAILY FRESH DATASETS
# ============================================================================
def check_new_kaggle_datasets():
    """Check for new funding datasets"""
    kaggle_csvs = [
        "https://raw.githubusercontent.com/DeepakKumarGS/Indian-Startup-Funding-/gh-pages/startup_funding.csv"
    ]
    
    for url in kaggle_csvs:
        try:
            df = pd.read_csv(url)
            # Check timestamp column or hash file
            latest_record = df.tail(1).to_dict('records')[0]
            text = json.dumps(latest_record, indent=2)
            ingest_if_new(text, "Kaggle Fresh Dataset",url=url, doc_type="kaggle_dataset")
        except:
            pass

# ============================================================================
# MAIN LOOP
# ============================================================================
def main_loop():
    """Runs forever"""
    logger.info("🚀 Dynamic scraper started - checking every 6 hours")
    init_dedup_db()
    
    while True:
        try:
            logger.info("🔄 Starting scrape cycle...")
            
            scrape_rss_feeds()
            scrape_growthlist()
            scrape_indian_startup_news()
            check_new_kaggle_datasets()
            
            logger.info("✅ Cycle complete - sleeping 6 hours")
            time.sleep(SCRAPE_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("🛑 Stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Cycle failed: {e}")
            time.sleep(300)  # Retry in 5 min

if __name__ == "__main__":
    main_loop()
