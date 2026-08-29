"""
Vercel serverless function: fetches a Boliga listing page SERVER-SIDE and
pulls out the numbers analyser.html needs (price, size, rooms, byggeår,
Ejerudgift, plus any BBR building-register fields Boliga's page shows -
see bbr_enrich.py for what that means and why).

Why this needs a real backend at all, when the rest of this project is
static files: a browser can't fetch an arbitrary external site directly -
Boliga's own API only allows cross-origin requests from boliga.dk itself,
and most sites either block automated requests outright or render their
numbers with JavaScript a plain fetch can't see. None of that applies to
a request from server to server, which is what this function does - it's
the one exception to this project's "no backend" design, and only exists
because Vercel happens to make a small function like this easy to add
alongside the static site.

Deliberately restricted to boliga.dk URLs only (not a generic URL
fetcher) - fetching arbitrary user-supplied URLs from a server is a real
SSRF risk if left open-ended.
"""

import json
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

ALLOWED_HOSTS = {"www.boliga.dk", "boliga.dk"}

APP_STATE_SCRIPT_RE = re.compile(r'<script id="boliga-app-state".*?</script>', re.DOTALL)
DETAIL_PAIR_RE = re.compile(r'detail-title">([^<]+)</div><div[^>]*class="detail-value">([^<]+)</div>')


def extract_number(pattern, text):
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(".", ""))
    except ValueError:
        return None


def scrape_boliga_listing(url):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    html = response.text

    title_match = re.search(r"<title>Til salg:\s*([^<]+)</title>", html)

    result = {
        "address": title_match.group(1).strip() if title_match else None,
        "price": extract_number(r"Udbudspris:\s*([\d.]+)\s*kr", html),
        "m2": extract_number(r"Fritidshus p[åa]\s*(\d+)\s*m", html),
        "rooms": extract_number(r"med\s*(\d+)\s*v[æa]relser", html),
        "ejerudgift_md": extract_number(r"Ejerudgift\s*([\d.]+)\s*kr\./md", html),
        "byggeaar": extract_number(r"Byggeår:\s*(\d{4})", html),
    }

    # Strip Boliga's big app-wide translation-strings blob first - same
    # reasoning as bbr_enrich.py - before pulling out any BBR fields the
    # page happens to show for this address.
    cleaned = APP_STATE_SCRIPT_RE.sub("", html)
    bbr = {}
    for title, value in DETAIL_PAIR_RE.findall(cleaned):
        bbr[title.strip()] = value.strip()
    result["bbr"] = bbr

    return result


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        target_url = (query.get("url") or [None])[0]

        if not target_url:
            self._send_json(400, {"error": "Mangler ?url= parameter"})
            return

        parsed = urlparse(target_url)
        if parsed.hostname not in ALLOWED_HOSTS:
            self._send_json(400, {"error": "Kun boliga.dk-links understøttes"})
            return

        try:
            data = scrape_boliga_listing(target_url)
        except requests.RequestException as error:
            self._send_json(502, {"error": f"Kunne ikke hente siden: {error}"})
            return

        if not data.get("price"):
            self._send_json(200, {"error": "Kunne ikke finde boligdata på denne side"})
            return

        self._send_json(200, data)
