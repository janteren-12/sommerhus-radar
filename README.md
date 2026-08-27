# Sommerhus Radar

A small tool that watches for new sommerhus (fritidshus / holiday home)
listings for sale in a set of Danish areas, and shows them on a simple
website you can open on your phone.

There's no database and no server that runs all the time. It's just:

1. A Python script (`scrape.py`) that checks Boliga.dk's listings and writes
   the results to a file: `docs/data.json`.
2. A plain HTML page (`docs/index.html`) that reads that file and displays
   it. No frameworks, no build step - you can open it by double-clicking it.
3. A GitHub Actions workflow that runs the script automatically once an
   hour and saves the updated file back into the repo.
4. GitHub Pages serves the `docs/` folder as a website, so the page is
   always showing the latest data without you doing anything.

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
| `scrape.py` | The scraper. Run with `python scrape.py`. |
| `areas.yaml` | The list of areas and postal codes to watch. Edit this to add/remove areas. |
| `config.yaml` | Optional filters (max price, min size, etc.) and politeness settings. |
| `docs/index.html` | The website. |
| `docs/data.json` | The data the website reads. Rewritten by the scraper every run - don't edit by hand. |
| `.github/workflows/scrape.yml` | Tells GitHub to run the scraper every hour. |
| `requirements.txt` | The two Python packages the scraper needs. |

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

## Phase 2 (not built yet)

The idea: for each area, count how many holiday homes are currently listed
*for rent* by the big Danish rental agencies - Novasol, Sol og Strand,
Feriepartner, DanCenter, and Esmark - and show that count as a "rental
demand score" on each for-sale card. The theory being: an area where
rental agencies list a lot of houses is an area with strong rental demand,
which matters if you're buying partly as a rental investment.

This hasn't been started. Some things to figure out when it's time:

- None of those five sites have a public API like Boliga's, so this would
  mean either scraping their search/listing pages directly (fragile - they
  can change their HTML any time, and scraping frequency will need the
  same polite-request approach used here) or checking whether any of them
  offer a partner/affiliate data feed instead.
  Sol og Strand, Novasol, and DanCenter are all under the same parent
  company (Awaze) as of a few years ago, so it's possible two or three of
  the five need only one scraping approach.
  Matching a rental listing to one of your defined areas will need to be
  done by postal code, same as the sale side.
- A sensible score is probably just a raw count of active rental listings
  per area per agency (or summed across agencies), refreshed on the same
  hourly cadence as the sale scraper, and stored in its own JSON file
  (e.g. `docs/rental_demand.json`) so a broken rental scrape can never
  block the sale-listings scrape from updating.
