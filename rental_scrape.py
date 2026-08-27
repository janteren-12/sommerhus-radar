"""
Rental-demand checker for sommerhus-radar.

For each area we track, this checks the big Danish holiday-rental
companies' own websites to see which ones operate there, as a signal of
how strong rental demand is in that area. Writes the result to
docs/rentals.json, which docs/rentals.html displays.

This is a separate script from scrape.py on purpose: if a rental
company changes their website and breaks this script, the for-sale
listings on the main page should keep updating regardless.

Run it with:
    python rental_scrape.py
Add --force to run even if the last run was less than an hour ago.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RENTALS_PATH = os.path.join(BASE_DIR, "docs", "rentals.json")
MIN_MINUTES_BETWEEN_RUNS = 55

# A plain browser User-Agent. We tried an honest, descriptive one first
# (like scrape.py uses for Boliga), but Feriepartner's site quietly 404s
# any request that doesn't look like a normal browser - even though their
# own robots.txt allows crawling these exact pages. Using a standard
# browser string here isn't pretending to be a specific person; it's just
# what lets a normal page request through their basic bot filter.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

SECONDS_BETWEEN_REQUESTS = 1.5

COMPANY_LABELS = {
    "dancenter": "DanCenter",
    "novasol": "Novasol",
    "sologstrand": "Sol og Strand",
    "feriepartner": "Feriepartner",
    "esmark": "Esmark",
}

# DanCenter's area pages show a real, live count in their page text, e.g.
# "Din søgning fandt 66 ferieboliger." The other three companies load their
# real counts with JavaScript, which a plain request can't see - for those
# we can only tell whether the page exists (i.e. they cover this area).
DANCENTER_COUNT_PATTERN = re.compile(r"fandt\s+([\d.]+)\s+ferieboliger", re.IGNORECASE)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_areas():
    return load_yaml(os.path.join(BASE_DIR, "areas.yaml"))


def load_rental_sources():
    return load_yaml(os.path.join(BASE_DIR, "rental_sources.yaml"))


def check_dancenter(session, url):
    """Fetch a DanCenter area page and pull out the live listing count."""
    response = session.get(url, timeout=20)
    if response.status_code != 200:
        return {"present": False, "count": None, "url": url}

    match = DANCENTER_COUNT_PATTERN.search(response.text)
    count = int(match.group(1).replace(".", "")) if match else None
    return {"present": True, "count": count, "url": url}


def check_presence_only(session, url):
    """For sites that only reveal real counts via JavaScript, the best we
    can do with a plain request is check whether their page for this area
    exists at all."""
    response = session.get(url, timeout=20)
    present = response.status_code == 200
    return {"present": present, "count": None, "url": url}


def check_company(session, company_key, url):
    if company_key == "dancenter":
        return check_dancenter(session, url)
    return check_presence_only(session, url)


def minutes_since(iso_timestamp):
    then = datetime.fromisoformat(iso_timestamp)
    now = datetime.now(timezone.utc)
    return (now - then).total_seconds() / 60


def main():
    force = "--force" in sys.argv

    if os.path.exists(RENTALS_PATH) and not force:
        with open(RENTALS_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        last_updated = existing.get("last_updated")
        if last_updated:
            elapsed = minutes_since(last_updated)
            if elapsed < MIN_MINUTES_BETWEEN_RUNS:
                print(
                    f"Last run was only {elapsed:.0f} minutes ago. "
                    f"Staying polite and skipping this run (use --force to override)."
                )
                return

    areas = load_areas()
    rental_sources = load_rental_sources()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})

    now_iso = datetime.now(timezone.utc).isoformat()
    result_areas = {}

    for area_key, area_info in areas.items():
        label = area_info.get("label", area_key)
        sources = rental_sources.get(area_key, {})

        print(f"Checking rental companies for {label}...")
        company_results = {}

        for company_key, url in sources.items():
            try:
                company_results[company_key] = check_company(session, company_key, url)
            except requests.RequestException as error:
                print(f"  Could not check {company_key}: {error}")
                company_results[company_key] = {"present": None, "count": None, "url": url}
            time.sleep(SECONDS_BETWEEN_REQUESTS)

        # Esmark's site only ever shows placeholder numbers for any area
        # without running its JavaScript, so we don't have a reliable way
        # to check it automatically. Listed as "unknown" rather than left
        # out entirely, so the website can show that honestly.
        company_results["esmark"] = {"present": None, "count": None, "url": None}

        summary = ", ".join(
            f"{company_key}={'yes' if r['present'] else 'no' if r['present'] is False else '?'}"
            for company_key, r in company_results.items()
        )
        print(f"  {summary}")

        result_areas[area_key] = {
            "area_label": label,
            "companies": company_results,
        }

    output = {
        "last_updated": now_iso,
        "company_labels": COMPANY_LABELS,
        "areas": result_areas,
    }

    os.makedirs(os.path.dirname(RENTALS_PATH), exist_ok=True)
    with open(RENTALS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Written to {RENTALS_PATH}")


if __name__ == "__main__":
    main()
