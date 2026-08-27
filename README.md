# Sommerhus Radar

A small tool that watches for new sommerhus (fritidshus / holiday home)
listings for sale in a set of Danish areas, and shows them on a simple
website you can open on your phone.

There's no database and no server that runs all the time. It's just:

1. A Python script (`scrape.py`) that checks Boliga.dk's listings and writes
   the results to a file: `docs/data.json`.
2. A second Python script (`rental_scrape.py`) that checks which big rental
   companies operate in each area, and writes `docs/rentals.json`.
3. A plain HTML site (`docs/index.html` plus `docs/rentals.html`) that reads
   those files and displays them. No frameworks, no build step - you can
   open it by double-clicking it.
4. A GitHub Actions workflow that runs both scripts automatically once an
   hour and saves the updated files back into the repo.
5. GitHub Pages (and, as of this update, also Vercel) serves the `docs/`
   folder as a website, so the page is always showing the latest data
   without you doing anything.

## How the "what's new" part works

The very first time the scraper sees a listing, it stamps it with
`first_seen` (the date and time). Every time after that, it leaves
`first_seen` alone, even if the listing's price or details change. The
website uses that timestamp to show a "NY" (new) badge on anything first
seen in the last 48 hours.

If a listing disappears from Boliga (most likely because it sold, or the
agent took it down), the scraper doesn't delete it. It gets marked
`"sold_or_removed": true` and stays in the data file, so you keep a full
history of what you've seen instead of it just vanishing.

## Files

| File | What it's for |
|---|---|
| `scrape.py` | The for-sale scraper. Run with `python scrape.py`. |
| `rental_scrape.py` | The rental-companies checker. Run with `python rental_scrape.py`. |
| `areas.yaml` | The list of areas and postal codes to watch. Edit this to add/remove areas. |
| `config.yaml` | Optional filters (max price, min size, etc.) and politeness settings. |
| `rental_sources.yaml` | Which page on each rental company's site covers each area. |
| `docs/index.html` | The main website (for-sale listings). |
| `docs/rentals.html` | The "which companies rent here" subpage. |
| `docs/data.json` | The for-sale data. Rewritten every run - don't edit by hand. |
| `docs/rentals.json` | The rental-companies data. Rewritten every run - don't edit by hand. |
| `.github/workflows/scrape.yml` | Tells GitHub to run both scripts every hour. |
| `requirements.txt` | The two Python packages the scrapers need. |
| `vercel.json`, `.vercelignore` | Tell Vercel this is a static site living in `docs/`, not a Python app. |

## Running it yourself

```
pip install -r requirements.txt
python scrape.py
```

Then open `docs/index.html` in a browser. Note: because browsers block a
local page from fetching a local JSON file for security reasons, opening
`index.html` by just double-clicking it may show "Kunne ikke hente
data.json". If that happens, run a tiny local web server from the project
folder instead:

```
python -m http.server 8000 --directory docs
```

and open `http://localhost:8000` in your browser. Once it's on GitHub
Pages this isn't an issue - it only affects testing on your own computer.

The scraper refuses to run again if the last run was less than about an
hour ago (to stay polite to Boliga's servers). Add `--force` to override
that, e.g. while testing changes.

## Putting it online (GitHub Pages)

1. Create a new repository on GitHub and push this folder to it.
2. On the repository page, click **Settings** (top menu bar).
3. In the left sidebar, click **Pages**.
4. Under "Build and deployment" → "Source", choose **Deploy from a
   branch**.
5. Under "Branch", pick your default branch (usually `main`) and change
   the folder dropdown from `/ (root)` to **`/docs`**. Click **Save**.
6. GitHub will show you a URL (something like
   `https://<your-username>.github.io/<repo-name>/`) - that's your site.
   It can take a minute or two to go live the first time.
7. Nothing else to do - the Actions workflow will keep `docs/data.json`
   updated every hour, and Pages will automatically serve whatever is in
   `docs/` on the default branch.

If the hourly runs aren't happening: go to the **Actions** tab on the repo
and check the "Scrape sommerhus listings" workflow has runs listed (not
greyed out/disabled), and open a run to see any error.

## Decisions made while building this (so you know what to expect)

- **Boliga's `propertyType=4`** is what fritidshus/sommerhus listings use.
  This isn't documented anywhere - I found it by querying the endpoint
  directly and checking that the results were actual holiday homes in
  known holiday-home areas (Blåvand, Bornholm, etc).
- **One postal code per API request.** Boliga's `zipcodeFrom`/`zipcodeTo`
  only support a numeric *range*, not an arbitrary list, and your areas
  have non-adjacent postal codes (e.g. Blåvand is 6857, 6853, 6854, 6830 -
  not a clean range). So the scraper asks Boliga once per postal code
  instead. With ~33 postal codes across all areas and a 1.5 second pause
  between requests, a full run takes roughly a minute.
- **The scraper double-checks property type itself.** While testing, I
  found that Boliga's API occasionally returns a listing of the wrong
  property type (a regular house or apartment) even when explicitly
  filtered to `propertyType=4` - it looks like sponsored/boosted listings
  can bypass the filter. The scraper throws these away itself rather than
  trusting the API completely.
- **User-Agent string** identifies the tool as a small personal script
  rather than pretending to be a regular browser, and politeness settings
  (1.5s between requests, one request at a time, refuses to re-run within
  an hour) are baked in as defaults in `config.yaml`.
- **Listing link format**: `https://www.boliga.dk/bolig/{id}/{slug}`.
  Verified this resolves correctly (redirects to Boliga's canonical page
  for that address) rather than guessing.
- **"NY" window is 48 hours** based on `first_seen`, per the spec. This is
  a fixed constant in `docs/index.html` (`NEW_WINDOW_HOURS`) if you want to
  change it later.
- **Design**: minimal, one accent colour (a muted green), rounded cards, no
  borders/shadows, single-column mobile-first layout, dark mode support via
  `prefers-color-scheme` since you'll mostly be opening this on a phone.
- **No database** - deliberately, per the brief. `docs/data.json` typically
  holds all currently-tracked listings (currently around 1,600+ across all
  11 areas), which is small enough that this approach scales fine for a
  personal tool. If that ever became a real problem, the fix would be
  archiving old `sold_or_removed` entries out of the live file rather than
  switching to a database.

## Phase 2: rental companies per area

`docs/rentals.html` (linked from the top of the main page) shows, for each
area, which of the big Danish rental companies operate there: DanCenter,
Novasol, Sol og Strand, and Feriepartner. It's driven by `rental_scrape.py`
and `rental_sources.yaml`, refreshed on the same hourly schedule as the
for-sale data.

What it actually shows, and why it's not a clean "5 companies, 1 number
each" table:

- **DanCenter** gives a real, live count ("66 boliger") - their area pages
  show the number in plain page text (`"Din søgning fandt 66
  ferieboliger."`), so this one is trustworthy and genuinely current.
- **Novasol, Sol og Strand, and Feriepartner** only show "Ja" (yes) or "Nej"
  (no) - whether the company has a page for that area at all, meaning they
  operate there. All three load their real listing *counts* with
  JavaScript after the page loads, which a plain Python script reading raw
  HTML can't see. Getting real numbers from these three would need a
  headless browser (e.g. Playwright) running real Chrome to render the
  page first - a much heavier dependency than the rest of this project, and
  something to add later if the presence-only view turns out not to be
  enough.
- **Esmark** isn't checked automatically at all. Its site returns the exact
  same placeholder numbers no matter what area you ask about until
  JavaScript runs, so a plain request can't even confirm whether it
  operates in an area, let alone count anything. `docs/rentals.html` shows
  a note about this rather than a made-up answer.
- All four companies' pages were checked against their own `robots.txt`
  before scraping - only publicly listed, crawlable pages are used
  (nothing behind a disallowed search/booking path).
- Feriepartner's server quietly returns 404 for requests that don't look
  like they come from a normal browser, even on pages their own
  `robots.txt` explicitly allows crawling - so `rental_scrape.py` uses an
  ordinary browser User-Agent string for its requests, unlike `scrape.py`'s
  more honest, descriptive one for Boliga (which Boliga has no problem
  with).

If you want real live counts from Novasol, Sol og Strand, and Feriepartner
too, the next step would be adding Playwright to `requirements.txt` and
having the GitHub Actions workflow install a headless Chromium browser -
that's a real jump in complexity and run time for this project, so it
wasn't done by default.
