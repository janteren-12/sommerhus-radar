"""
sommerhus-radar scraper.

Talks to Boliga's public (but undocumented) search API, pulls fritidshus
(sommerhus) listings for the postal codes listed in areas.yaml, and writes
everything to docs/data.json so the website can show it.

Run it with:
    python scrape.py
Add --force to run even if the last run was less than an hour ago.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "docs", "data.json")

API_URL = "https://api.boliga.dk/api/v2/search/results"

# 4 is Boliga's internal code for "fritidshus" (sommerhus). We found this by
# trying the endpoint directly and checking the results.
FRITIDSHUS_PROPERTY_TYPE = 4

# A normal browser-style user agent plus a short note about what we're doing.
# Being upfront and polite about the fact that this is a small personal
# script, not something trying to hide.
USER_AGENT = (
    "sommerhus-radar/1.0 (personal hobby project, checks a short list of "
    "postal codes hourly for new holiday-home listings; not for resale)"
)

MAX_PAGES_PER_ZIPCODE = 20  # safety cap so a bug can't loop forever
MIN_MINUTES_BETWEEN_RUNS = 55


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_areas():
    return load_yaml(os.path.join(BASE_DIR, "areas.yaml"))


def load_config():
    return load_yaml(os.path.join(BASE_DIR, "config.yaml")) or {}


def load_existing_data():
    if not os.path.exists(DATA_PATH):
        return None
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_page(session, zipcode, page):
    params = {
        "propertyType": FRITIDSHUS_PROPERTY_TYPE,
        "zipcodeFrom": zipcode,
        "zipcodeTo": zipcode,
        "page": page,
        "pageSize": 100,
        # Without an explicit sort, Boliga's API tends to mix in unrelated
        # sponsored listings on page 1. Asking for a sort mostly avoids that
        # (we still double check propertyType ourselves below, just in case).
        "sort": "daysForSale-a",
    }
    response = session.get(API_URL, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_all_listings_for_zipcode(session, zipcode, seconds_between_requests):
    """Fetch every page of fritidshus results for one postal code."""
    all_results = []
    page = 1
    while page <= MAX_PAGES_PER_ZIPCODE:
        data = fetch_page(session, zipcode, page)
        results = data.get("results", [])

        # Defensive filter: we've seen Boliga slip in a listing of the wrong
        # property type even when we asked for fritidshus only. Just drop
        # anything that isn't actually a fritidshus.
        results = [r for r in results if r.get("propertyType") == FRITIDSHUS_PROPERTY_TYPE]
        all_results.extend(results)

        total_pages = data.get("meta", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(seconds_between_requests)

    return all_results


def build_link(listing):
    ou_address = listing.get("ouAddress") or ""
    return f"https://www.boliga.dk/bolig/{listing['id']}/{ou_address}"


def passes_filters(listing, config):
    """Apply the optional filters from config.yaml. Any filter left as
    null/None in the config is simply skipped."""
    price = listing.get("price")
    m2 = listing.get("size")
    grund_m2 = listing.get("lotSize")
    days_on_market = listing.get("daysForSale")
    text_to_check = f"{listing.get('street', '')} {listing.get('city', '')}".lower()

    max_price = config.get("max_price")
    if max_price and price and price > max_price:
        return False

    min_m2 = config.get("min_m2")
    if min_m2 and m2 and m2 < min_m2:
        return False

    min_grund_m2 = config.get("min_grund_m2")
    if min_grund_m2 and grund_m2 and grund_m2 < min_grund_m2:
        return False

    max_days_on_market = config.get("max_days_on_market")
    if max_days_on_market and days_on_market and days_on_market > max_days_on_market:
        return False

    for keyword in config.get("exclude_keywords") or []:
        if keyword.lower() in text_to_check:
            return False

    return True


def build_record(listing, area_key, area_label, existing_by_id, now_iso):
    listing_id = listing["id"]
    existing = existing_by_id.get(listing_id)
    first_seen = existing["first_seen"] if existing else now_iso

    return {
        "id": listing_id,
        "address": listing.get("street"),
        "postnummer": listing.get("zipCode"),
        "city": listing.get("city"),
        "area": area_key,
        "area_label": area_label,
        "price": listing.get("price"),
        "m2": listing.get("size"),
        "grund_m2": listing.get("lotSize"),
        "byggeaar": listing.get("buildYear"),
        "kr_per_m2": listing.get("squaremeterPrice"),
        "dage_paa_markedet": listing.get("daysForSale"),
        "link": build_link(listing),
        "first_seen": first_seen,
        "sold_or_removed": False,
    }


def minutes_since(iso_timestamp):
    then = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(timezone.utc)
    return (now - then).total_seconds() / 60


def main():
    force = "--force" in sys.argv

    config = load_config()
    areas = load_areas()
    existing_data = load_existing_data()

    existing_by_id = {}
    if existing_data:
        for record in existing_data.get("listings", []):
            existing_by_id[record["id"]] = record

        last_updated = existing_data.get("last_updated")
        if last_updated and not force:
            elapsed = minutes_since(last_updated)
            if elapsed < MIN_MINUTES_BETWEEN_RUNS:
                print(
                    f"Last run was only {elapsed:.0f} minutes ago. "
                    f"Staying polite and skipping this run (use --force to override)."
                )
                return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    seconds_between_requests = config.get("seconds_between_requests", 1.5)
    now_iso = datetime.now(timezone.utc).isoformat()

    seen_ids = set()
    fresh_records = []

    for area_key, area_info in areas.items():
        label = area_info.get("label", area_key)
        zipcodes = area_info.get("zipcodes", [])

        for zipcode in zipcodes:
            print(f"Fetching {label} ({zipcode})...")
            try:
                raw_listings = fetch_all_listings_for_zipcode(
                    session, zipcode, seconds_between_requests
                )
            except requests.RequestException as error:
                print(f"  Could not fetch postal code {zipcode}: {error}")
                continue

            kept = 0
            for listing in raw_listings:
                if not passes_filters(listing, config):
                    continue
                record = build_record(listing, area_key, label, existing_by_id, now_iso)
                seen_ids.add(record["id"])
                fresh_records.append(record)
                kept += 1

            print(f"  {len(raw_listings)} listings found, {kept} kept after filters")
            time.sleep(seconds_between_requests)

    # Anything we knew about before that we didn't see this run has probably
    # been sold or pulled off the market. We never delete listings - we just
    # flag them, so the history (and first_seen dates) stays intact.
    for listing_id, existing_record in existing_by_id.items():
        if listing_id not in seen_ids:
            existing_record["sold_or_removed"] = True
            fresh_records.append(existing_record)

    fresh_records.sort(key=lambda r: r["first_seen"], reverse=True)

    output = {
        "last_updated": now_iso,
        "listings": fresh_records,
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    active_count = sum(1 for r in fresh_records if not r["sold_or_removed"])
    removed_count = len(fresh_records) - active_count
    print(f"\nDone. {active_count} active listings, {removed_count} marked sold/removed.")
    print(f"Written to {DATA_PATH}")


if __name__ == "__main__":
    main()
