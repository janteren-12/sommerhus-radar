"""
Fetches "realized" (actually sold) fritidshus prices from Boliga, for use
as comparables in the mispricing model. This is a separate, much heavier
job than the hourly scrape.py, so it caches its result to sold_cache.json
and only refreshes once a week.

Boliga's sold-prices endpoint is the same shape as the for-sale one, but
doesn't include lot size or energy class. Those are fetched separately,
one extra request per sold record, from the estate detail endpoint. That
adds up to several thousand requests for a nationwide 24-month window, so
unlike every other script in this project, this one uses a small pool of
concurrent requests (5 at a time) rather than one at a time - otherwise a
weekly refresh would take multiple hours. See README for why that
trade-off was made here specifically.

Run it with:
    python sold_cache.py
Add --force to refresh even if the cache is less than a week old.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
import yaml

from coastal_distance import distance_to_coast_m

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "sold_cache.json")

API_URL = "https://api.boliga.dk/api/v2/sold/search/results"
ESTATE_URL = "https://api.boliga.dk/api/v2/estate/{id}"

FRITIDSHUS_PROPERTY_TYPE = 4
MONTHS_OF_HISTORY = 24
MIN_DAYS_BETWEEN_REFRESH = 6.5 * 24 * 60  # about a week, in minutes
MAX_PAGES_PER_ZIPCODE = 40  # safety cap
DETAIL_FETCH_WORKERS = 5

# The sold-search endpoint turns out to have its own strict rate limit -
# found by watching its X-RateLimit-* response headers: 5 requests per
# roughly 11 seconds, separate from (and much tighter than) the for-sale
# search endpoint scrape.py uses. 2.5s between requests keeps comfortably
# under that. The estate detail endpoint used for backfill showed no such
# limit even under a burst of requests, which is why only that part uses
# a thread pool.
SOLD_SEARCH_SECONDS_BETWEEN_REQUESTS = 2.5
MAX_RATE_LIMIT_RETRIES = 5

# Only genuine arm's-length sales make sense as market comparables. Family
# sales in particular tend to be well below market value.
ARMS_LENGTH_SALE_TYPES = {"Alm. Salg"}

USER_AGENT = (
    "sommerhus-radar/1.0 (personal hobby project, refreshes a weekly cache "
    "of sold-price comparables for a small list of postal codes)"
)


def load_areas():
    with open(os.path.join(BASE_DIR, "areas.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_existing_cache():
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def minutes_since(iso_timestamp):
    then = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(timezone.utc)
    return (now - then).total_seconds() / 60


def get_with_rate_limit_retry(session, url, params):
    """GET with a retry loop for the sold-search endpoint's strict rate
    limit: if we get a 429, wait until the endpoint's own X-RateLimit-Reset
    time (plus a one second buffer) and try again, rather than guessing at
    a backoff delay."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        response = session.get(url, params=params, timeout=20)
        if response.status_code != 429:
            response.raise_for_status()
            return response

        reset_at = response.headers.get("x-ratelimit-reset")
        if reset_at:
            wait_seconds = max(1.0, float(reset_at) - time.time()) + 1.0
        else:
            wait_seconds = 5.0 * (attempt + 1)
        print(f"  Rate limited, waiting {wait_seconds:.0f}s...")
        time.sleep(wait_seconds)

    raise requests.RequestException(f"Still rate limited after {MAX_RATE_LIMIT_RETRIES} retries: {url}")


def fetch_sold_for_zipcode(session, zipcode, cutoff_date, seconds_between_requests):
    """Fetch sold fritidshus records for one postal code, stopping once
    results fall older than cutoff_date (results come back newest-first)."""
    records = []
    page = 1
    while page <= MAX_PAGES_PER_ZIPCODE:
        params = {
            "propertyType": FRITIDSHUS_PROPERTY_TYPE,
            "zipcodeFrom": zipcode,
            "zipcodeTo": zipcode,
            "page": page,
            "pageSize": 100,
        }
        response = get_with_rate_limit_retry(session, API_URL, params)
        data = response.json()
        results = data.get("results", [])
        if not results:
            break

        hit_cutoff = False
        for r in results:
            if r.get("propertyType") != FRITIDSHUS_PROPERTY_TYPE:
                continue
            sold_date = datetime.fromisoformat(r["soldDate"].replace("Z", "+00:00"))
            if sold_date < cutoff_date:
                hit_cutoff = True
                break
            records.append(r)

        if hit_cutoff:
            break

        total_pages = data.get("meta", {}).get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(seconds_between_requests)

    return records


def fetch_estate_detail(session, estate_id):
    response = session.get(ESTATE_URL.format(id=estate_id), timeout=20)
    response.raise_for_status()
    return response.json()


def backfill_lot_and_energy(session, records):
    """Adds lotSize and energyClass to each record that has a real
    estateId, using a small thread pool since this is thousands of
    requests - see the module docstring for why that's an exception to
    this project's usual one-at-a-time rule."""
    needing_detail = [r for r in records if r.get("estateId")]
    print(
        f"Fetching lot size / energy class for {len(needing_detail)} of "
        f"{len(records)} sold records ({DETAIL_FETCH_WORKERS} at a time)..."
    )

    def fetch_one(record):
        try:
            detail = fetch_estate_detail(session, record["estateId"])
            record["lotSize"] = detail.get("lotSize")
            record["energyClass"] = detail.get("energyClass")
        except requests.RequestException:
            record["lotSize"] = None
            record["energyClass"] = None
        return record

    done = 0
    with ThreadPoolExecutor(max_workers=DETAIL_FETCH_WORKERS) as pool:
        futures = [pool.submit(fetch_one, r) for r in needing_detail]
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 200 == 0:
                print(f"  ...{done}/{len(needing_detail)}")

    for r in records:
        if "lotSize" not in r:
            r["lotSize"] = None
            r["energyClass"] = None

    return records


def add_coast_distance(records):
    for r in records:
        lat, lon = r.get("latitude"), r.get("longitude")
        r["distance_to_coast_m"] = (
            round(distance_to_coast_m(lat, lon)) if lat and lon else None
        )
    return records


def main():
    force = "--force" in sys.argv

    existing = load_existing_cache()
    if existing and not force:
        elapsed = minutes_since(existing["fetched_at"])
        if elapsed < MIN_DAYS_BETWEEN_REFRESH:
            days = elapsed / (24 * 60)
            print(
                f"Sold-price cache is only {days:.1f} days old. Sold prices "
                f"barely move week to week, so skipping (use --force to refresh anyway)."
            )
            return

    areas = load_areas()
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=MONTHS_OF_HISTORY * 30)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    seconds_between_requests = SOLD_SEARCH_SECONDS_BETWEEN_REQUESTS
    all_records = []
    seen_estate_ids = set()

    for area_key, area_info in areas.items():
        label = area_info.get("label", area_key)
        for zipcode in area_info.get("zipcodes", []):
            print(f"Fetching sold prices: {label} ({zipcode})...")
            try:
                records = fetch_sold_for_zipcode(
                    session, zipcode, cutoff_date, seconds_between_requests
                )
            except requests.RequestException as error:
                print(f"  Could not fetch postal code {zipcode}: {error}")
                continue

            kept = 0
            for r in records:
                # The same address can show up under more than one
                # postal-code query if it's near a boundary; guard against
                # double-counting.
                dedup_key = r.get("guid") or (r["estateId"], r["soldDate"])
                if dedup_key in seen_estate_ids:
                    continue
                seen_estate_ids.add(dedup_key)
                r["area"] = area_key
                r["area_label"] = label
                all_records.append(r)
                kept += 1

            print(f"  {len(records)} sold in last {MONTHS_OF_HISTORY} months, {kept} new")
            time.sleep(seconds_between_requests)

    all_records = backfill_lot_and_energy(session, all_records)
    all_records = add_coast_distance(all_records)

    arms_length_count = sum(1 for r in all_records if r.get("saleType") in ARMS_LENGTH_SALE_TYPES)
    print(
        f"\n{len(all_records)} sold records total, "
        f"{arms_length_count} are arm's-length sales (used for the pricing model)."
    )

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "months_of_history": MONTHS_OF_HISTORY,
        "records": all_records,
    }

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Written to {CACHE_PATH}")


if __name__ == "__main__":
    main()
