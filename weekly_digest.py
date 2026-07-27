"""
Weekly digest job for Atelier subscriptions.

Standalone script — not part of the FastAPI app. Intended to be triggered by
a Replit Scheduled Deployment on a weekly cron: `python weekly_digest.py`.

For each active subscription:
1. Subscriptions sharing the same (city, search_queries) are grouped so each
   unique search is scraped from Marktplaats only once per run ("group
   scraping"), then fanned out to every subscriber in that group.
2. Listings already sent to a subscription are filtered out.
3. The remaining new matches are re-ranked and explained with the existing
   AI pipeline (ai_client.py).
4. A digest email is sent via Resend, skipping subscriptions with zero new
   matches so nobody gets an empty email.
"""

import os
import logging
from collections import defaultdict

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from jinja2 import Environment, FileSystemLoader

from marktplaats import search_marktplaats_listings
from ai_client import retrieve_candidates, explain_matches

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weekly_digest")

DATABASE_URL = os.environ.get("DATABASE_URL")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "Atelier <onboarding@resend.dev>")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

jinja_env = Environment(loader=FileSystemLoader("templates"))


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def load_active_subscriptions(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, email, city, style_profile, search_queries, unsubscribe_token
            FROM subscriptions
            WHERE is_active = TRUE
        """)
        return cur.fetchall()


def load_sent_ids(conn, subscription_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT listing_id FROM sent_listings WHERE subscription_id = %s",
            (subscription_id,)
        )
        return {row[0] for row in cur.fetchall()}


def record_sent(conn, subscription_id, listing_ids):
    if not listing_ids:
        return
    with conn.cursor() as cur:
        for lid in listing_ids:
            cur.execute("""
                INSERT INTO sent_listings (subscription_id, listing_id)
                VALUES (%s, %s)
                ON CONFLICT (subscription_id, listing_id) DO NOTHING
            """, (subscription_id, lid))
        cur.execute(
            "UPDATE subscriptions SET last_sent_at = now() WHERE id = %s",
            (subscription_id,)
        )
    conn.commit()


def group_key(sub):
    queries = sub["search_queries"] or []
    return (sub["city"], tuple(sorted(queries)))


def styles_description(style_profile):
    styles = (style_profile or {}).get("styles") or []
    if not styles:
        return None
    return ", ".join(styles[:2])


def send_email(to_email, subject, html):
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set — cannot send email")

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def process_subscription(conn, sub, listings) -> bool:
    """Returns True if a digest email was sent for this subscription."""
    sent_ids = load_sent_ids(conn, sub["id"])
    new_listings = [l for l in listings if l["id"] not in sent_ids]

    if not new_listings:
        logger.info(f"No new matches for {sub['email']}, skipping")
        return False

    style_profile = sub["style_profile"] or {}

    if len(new_listings) > 5:
        ranked = retrieve_candidates(style_profile, new_listings, top_k=8)
    else:
        ranked = new_listings

    pieces = ranked[:6]
    try:
        pieces = explain_matches(style_profile, pieces)
    except Exception as e:
        logger.warning(f"Explanation generation failed for {sub['email']}: {e}")

    unsubscribe_url = f"{APP_BASE_URL}/unsubscribe?token={sub['unsubscribe_token']}"
    template = jinja_env.get_template("email_digest.html")
    html = template.render(
        pieces=pieces,
        city=sub["city"],
        styles_desc=styles_description(style_profile),
        unsubscribe_url=unsubscribe_url,
    )

    count = len(pieces)
    subject = f"✨ {count} new piece{'s' if count != 1 else ''} match your vibe"

    send_email(sub["email"], subject, html)
    logger.info(f"Sent digest to {sub['email']}: {count} pieces")

    record_sent(conn, sub["id"], [p["id"] for p in pieces])
    return True


def run():
    conn = get_db_connection()
    try:
        subscriptions = load_active_subscriptions(conn)
    except Exception as e:
        logger.error(f"Failed to load subscriptions: {e}")
        conn.close()
        return

    if not subscriptions:
        logger.info("No active subscriptions, nothing to do")
        conn.close()
        return

    # Group scraping: one Marktplaats search per unique (city, queries) combo,
    # shared across every subscription that matches it, instead of one
    # scrape per subscriber.
    groups = defaultdict(list)
    for sub in subscriptions:
        groups[group_key(sub)].append(sub)

    logger.info(f"{len(subscriptions)} active subscriptions across {len(groups)} unique search groups")

    sent_count = 0
    for (city, queries), subs in groups.items():
        query_list = list(queries)
        if query_list:
            logger.info(f"Scraping group: city={city} queries={query_list} (shared by {len(subs)} subscription(s))")
            listings = search_marktplaats_listings(query_list, city)
        else:
            listings = []

        for sub in subs:
            try:
                if process_subscription(conn, sub, listings):
                    sent_count += 1
            except Exception as e:
                logger.error(f"Failed processing subscription {sub['id']} ({sub['email']}): {e}")

    conn.close()
    logger.info(f"Digest run complete, emails sent: {sent_count}")


if __name__ == "__main__":
    run()
