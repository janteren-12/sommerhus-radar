"""
Adds official building-register (BBR) details to a listing, by reading
them straight off Boliga's own listing page rather than querying BBR
directly.

Why not the real BBR API (Datafordeler)? Full access requires registering
a service account, which itself requires MitID Erhverv (a Danish business
digital ID) - something only the site's owner can set up, not something
this script can do on its own. Boliga, however, already has its own BBR
data agreement and renders some of it straight into its listing pages'
HTML (server-rendered, no JavaScript needed to see it) - toilet/bathroom
facilities, exterior wall material, roof material, and sometimes more.
This reads that instead.

Coverage genuinely varies per listing - some houses show several fields,
others (especially still-under-construction new builds) show none at all,
because BBR itself has nothing registered for them yet. This isn't a bug
in this script; it reflects what's actually in the register.

This is deliberately ON DEMAND, not run automatically. Fetching every
listing's own page just to check for BBR data adds real load for
information most listings won't even end up showing, so this only runs
for a specific listing you (or you asking Claude) actually care about -
never automatically in the hourly workflow.

Usage:
    python bbr_enrich.py --id 2360854
    python bbr_enrich.py --address "Pumavej 20"
    python bbr_enrich.py --all     # every active listing - slow, ~1.5s each,
                                    # only run this yourself if you really want
                                    # BBR data for everything at once
"""

import argparse
import json
import os
import re
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "docs", "data.json")

SECONDS_BETWEEN_REQUESTS = 1.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

APP_STATE_SCRIPT_RE = re.compile(r'<script id="boliga-app-state".*?</script>', re.DOTALL)
DETAIL_PAIR_RE = re.compile(r'detail-title">([^<]+)</div><div[^>]*class="detail-value">([^<]+)</div>')


def fetch_bbr_fields(session, url):
    """Returns a dict of BBR field name -> value for one listing's Boliga
    page, or an empty dict if none are shown for this address."""
    response = session.get(url, timeout=20)
    response.raise_for_status()
    html = response.text

    # Strip Boliga's big app-wide translation-strings blob first - it's
    # not listing-specific data, and some of its text would otherwise look
    # like real content.
    cleaned = APP_STATE_SCRIPT_RE.sub("", html)

    fields = {}
    for title, value in DETAIL_PAIR_RE.findall(cleaned):
        fields[title.strip()] = value.strip()
    return fields


def enrich_listing(session, listing):
    try:
        fields = fetch_bbr_fields(session, listing["link"])
        listing["bbr"] = fields
        listing["bbr_checked"] = True
        return fields
    except requests.RequestException as error:
        print(f"  Could not fetch {listing['link']}: {error}")
        return None


def find_listings(data, listing_id=None, address_contains=None):
    active_listings = [l for l in data["listings"] if not l["sold_or_removed"]]
    if listing_id is not None:
        return [l for l in active_listings if l["id"] == listing_id]
    if address_contains is not None:
        needle = address_contains.lower()
        return [l for l in active_listings if needle in (l.get("address") or "").lower()]
    return active_listings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", type=int, help="Boliga listing id to fetch BBR data for")
    target.add_argument("--address", type=str, help="Fetch the listing(s) whose address contains this text")
    target.add_argument("--all", action="store_true", help="Fetch every active listing (slow - see module docstring)")
    args = parser.parse_args()

    if not os.path.exists(DATA_PATH):
        print("docs/data.json not found - run scrape.py first.")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if args.all:
        targets = find_listings(data)
    elif args.id is not None:
        targets = find_listings(data, listing_id=args.id)
    else:
        targets = find_listings(data, address_contains=args.address)

    if not targets:
        print("No matching active listing found.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for i, listing in enumerate(targets):
        fields = enrich_listing(session, listing)
        if fields is not None:
            label = f"{listing.get('address')}, {listing.get('postnummer')} {listing.get('city')}"
            if fields:
                print(f"{label}:")
                for k, v in fields.items():
                    print(f"  {k}: {v}")
            else:
                print(f"{label}: no BBR data registered for this address.")

        if i < len(targets) - 1:
            time.sleep(SECONDS_BETWEEN_REQUESTS)

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nWritten back to {DATA_PATH}")


if __name__ == "__main__":
    main()
