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
| `.github/workflows/scrape.yml` | Tells GitHub to run the scraper, rental checker, and scoring engine every hour. |
| `.github/workflows/sold_cache.yml` | Tells GitHub to refresh the sold-price cache once a week. |
| `requirements.txt` | The Python packages everything needs. |
| `vercel.json`, `.vercelignore` | Tell Vercel this is a static site living in `docs/`, not a Python app. |
| `sold_cache.py` | Fetches sold-price comparables from Boliga. Run with `python sold_cache.py`. |
| `mispricing.py` | Fits the pricing model and predicts each listing's "fair" price. |
| `coastal_distance.py` | How far a point is from the Danish coastline, in metres. |
| `yield_calc.py` | The net rental yield calculation, as a standalone function. |
| `motivation.py` | The seller-motivation sub-score. |
| `composite.py` | Combines everything into the final 0-100 score. |
| `score.py` | Runs the whole scoring pipeline and writes the scores into `docs/data.json`. |
| `sold_cache.json` | Cached sold-price data. Rewritten weekly - don't edit by hand. |
| `rental_benchmarks.yaml` | **Edit this yourself** - typical weekly rental prices per area (see below). |
| `flags.yaml` | **Edit this yourself** - manual veto flags per listing (see below). |
| `data/coastline_denmark.geojson` | The Danish coastline shape, downloaded once. See `data/README.md`. |

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
- **Financial filters**: price reduction, days on market, price/m², down
  payment, monthly owner costs ("Ejerudgift"), and price-vs-area-average are
  all real numbers - either fields Boliga's API already returns per listing
  (`priceChangePercentTotal`, `downPayment`, and a field literally called
  `exp` that turned out to be Ejerudgift once checked against a real
  listing page), or computed directly from your own tracked listings
  (the area average is just the mean kr/m² across everything currently
  active in that area, recalculated by `scrape.py` every run). Two fields
  that looked promising in Boliga's raw response - `evaluationPrice`
  (public valuation) and `lastSoldPrice`/`lastSoldDate` (sale history) -
  turned out to always be zero/empty across every listing checked, so
  those aren't shown; showing them would mean showing a made-up number.
  There's no mortgage payment estimate, transaction cost estimate, or
  rental income/yield on the site - those would need real assumptions
  (interest rate, loan term) or data sources that don't exist publicly,
  and weren't part of what was asked for in this pass.
- **Håndværkertilbud detection**: "håndværkertilbud" (a discounted,
  fixer-upper sale arrangement) isn't a structured field anywhere in
  Boliga's data - it's something an agent writes in the listing's own
  text. Rather than fetching and scanning every listing's full page (slow,
  and fragile since Boliga's HTML structure can change), `scrape.py` makes
  one extra request per run to Boliga's own search with
  `q=håndværkertilbud`, and flags any of your tracked listings whose id
  comes back in that result. Confirmed this is a real search (not
  decoration) by testing a nonsense word against it first (0 results)
  compared to a common word like "udsigt" (2,369 results) - and confirmed
  it's checking more than just the visible page text, since the exact
  phrase doesn't always appear in a matched listing's rendered
  "Beskrivelse" section (Boliga sometimes shows its own auto-generated
  summary there instead of the agent's original text, but the search
  index still seems to see the original). One extra request per run,
  regardless of how many listings you're tracking.
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

## Phase 3: the deal-scoring engine

Every active listing on the site now gets a 0-100 score, shown big and bold
on its card, plus a plain-language reason line and a "Se score-detaljer"
button that expands the full breakdown.

**Before you rely on this for anything: read the "What the score is (and
isn't)" section below.** It's also on every card and in the score
breakdown, not just here.

### Where the score comes from

The score is a weighted combination of three independent things, each
turned into a percentile rank within the current pool of listings before
being combined (not a raw z-score - sommerhus prices are heavily
right-skewed by a handful of very expensive liebhaverhuse, and a z-score
would let those few houses distort everyone else's score):

| Component | Weight | What it measures |
|---|---|---|
| Mispricing | 40% | Is the asking price cheap or expensive vs. what similar recently-sold houses suggest it should cost? |
| Nettoafkast | 30% | If rented out through a bureau, would it earn a decent return after real Danish taxes and costs? |
| Sælgers motivation | 20% | Is there room to negotiate - long time on market, price cuts, a relist, an off-season listing? |
| Kvalitet | 10% | Newer construction and a better energy label. |

Change the weights in `config.yaml` under `score_weights` if you disagree
with this balance.

**Mispricing** comes from a hedonic regression - a statistical model that
learns typical prices from real recent sales, then compares each live
listing's asking price to what a house with its exact characteristics
"should" cost:

```
log(price) = b0 + b1·log(size) + b2·log(lot_size) + b3·build_year
           + b4·energy_label + b5·log(distance_to_coast) + b6·postnummer
```

Fitted on `sold_cache.py`'s data: sold fritidshuse in your tracked postal
codes from the last 24 months, restricted to genuine arm's-length sales
(Boliga's sold-price data separately marks family sales and a vague
"other" category, both excluded as unreliable market comparables). As of
the last run, that's **6,026 sold houses** feeding the model.

A few things worth knowing about the model itself:

- **Energy label is missing for ~85% of sold sommerhuse** - older, small
  secondary homes are very often never rated. Requiring a real label would
  have thrown away almost the entire dataset, so a missing/unrecognised
  label gets a neutral mid-scale value plus a separate "was it even rated"
  indicator, rather than being dropped. The ~15% that do have a label still
  pull real signal from it (bad label → statistically significant negative
  effect on price).
- **Distance to coast is a genuinely strong driver** - its coefficient is
  large, highly statistically significant, and in the expected direction
  (further from the sea = cheaper), which is exactly why the brief asked
  for it specifically instead of ranking on kr/m² alone. kr/m² by itself
  can't tell a big beachfront plot from a small one 5km inland; this
  model can.
- **A postnummer with fewer than 50 comps gets pooled with its whole
  area** (the same grouping as `areas.yaml`) rather than getting its own
  unreliable estimate. The card says so when this happens.
- **Overall R² is 0.538**, and per-postnummer R² (printed by
  `mispricing.py`/`score.py` on every run) is below the 0.6
  "meaningful residuals" threshold for almost every single postnummer -
  usually in the 0.2-0.5 range. This is a real, honest result, not a bug:
  five structural variables (size, plot, age, energy label, coast
  distance) simply can't explain most of what makes one sommerhus worth
  more than a very similar-looking one next door. Condition, view, noise,
  layout, kerb appeal - none of that is in Boliga's data. **This is exactly
  why the disclaimer below matters and is shown prominently, not buried.**

**Nettoafkast** is `yield_calc.py`'s standalone function, using the 2026
Danish rules for renting a sommerhus out through a bureau (skematisk
metode). It needs `rental_benchmarks.yaml` filled in for an area before it
can compute anything for listings there - see "Setup you need to do"
below. Important caveats, also printed on every card that shows a yield:

- **Ejendomsværdiskat is charged for the whole year** under the skematiske
  metode, even for weeks the house was rented out - this calculation
  reflects that (it doesn't prorate the tax down for rental weeks).
- **Confirm with a revisor whether your bureau reports gross booking
  value or your net payout** to SKAT - this changes what number the tax
  calculation should actually be based on, and this project can't know
  which one applies to your specific contract.
- **There's no real "building value" figure available** - Boliga's
  public-valuation field is always empty for these listings (see the
  "Financial filters" section above) - so the 1.25%/year maintenance
  reserve is calculated against the asking price itself, which overstates
  maintenance cost for an expensive plot with a modest house on it, and
  understates it the other way around.

**Sælgers motivation** combines five signals Boliga doesn't compute for
you but this project already tracks over time: how long the listing has
been up vs. similar houses nearby, the cumulative price cut, how many
*separate* times the price was cut (`scrape.py` counts this itself, run
over run - Boliga only exposes the cumulative total), whether it was ever
pulled and relisted (also tracked run over run), and whether it was first
listed in the Oct-Feb off-season. See `motivation.py` for the exact
weights.

**Kvalitet** is just build year and energy label - the brief's third
factor, renovation year, isn't in Boliga's structured data anywhere, so it
was left out rather than estimated. The 10% weight is split evenly across
the two factors that are actually available.

### Veto flags (`flags.yaml`)

None of these six things are visible in Boliga's data - they need a human
to notice them from the listing text, a map, or an actual visit:
`lejet_grund`, `kloakering_paa_vej`, `strandbeskyttelse`,
`kystnedbrydning`, `udlejning_forbudt`, and
`elvarme_daarligt_energimaerke` (which you don't need to set by hand -
any listing with energy label E, F, or G is auto-flagged, since electric
heating with a poor label usually means real running costs; override it
to `false` in `flags.yaml` for a specific listing if you've confirmed
that's not actually a problem there).

Anything flagged drops out of the scored/ranked list entirely and shows
instead in a separate, greyed-out "Udelukket" section at the bottom of the
page - kept, not deleted, but out of the way so it doesn't crowd out
houses you can actually compare fairly.

### Setup you need to do

The scoring engine works out of the box for mispricing and motivation, but
**yield won't show up for any area until you fill in
`rental_benchmarks.yaml`** - open that file, and for each area look up a
few comparable houses on Novasol or Sol og Strand in that postnummer, and
fill in a typical high-season and low-season week price. This is
deliberately manual (see the "Phase 2" section above for why the rental
companies' real prices can't be scraped).

### What the score is (and isn't)

**The score is a filter for where to spend a Saturday, not a decision.**
A large negative mispricing residual usually means the model is missing a
variable it has no way to see - condition, sea view, road noise, an
awkwardly shaped plot - not that a bargain was found. Given the
per-postnummer R² figures above, treat the mispricing number as a rough
steer, not a valuation. Always go look at the actual house, and its actual
listing text, before acting on any of this.

### Running the scoring pipeline yourself

```
python sold_cache.py      # weekly job - fetches sold-price comparables (slow: ~10-15 min)
python mispricing.py      # optional - just prints the model report, doesn't change any files
python score.py           # the actual scoring step - reads docs/data.json, writes scores back into it
```

`sold_cache.py` refuses to re-run within about a week unless you pass
`--force`, same pattern as the hourly scraper's one-hour guard.

One more honest tradeoff: `sold_cache.json` (~7MB) is now committed weekly,
and `docs/data.json` (~4.6MB, up from under 1MB before scoring - each
listing now carries its 5 nearest comparables and full score breakdown) is
committed hourly. Git compresses repeated commits of a mostly-unchanged
file reasonably well, but this repo's history will grow noticeably faster
than before. Not a problem worth solving pre-emptively for a personal
project, but if it ever becomes one, the fix is squashing history
periodically rather than changing the file format.

One implementation note: `sold_cache.py` is the one script in this project
that doesn't make requests strictly one at a time. Backfilling lot size
and energy class needs one extra request per sold record (several thousand
for a 24-month nationwide window), and Boliga's estate-detail endpoint
showed no rate limiting even under a burst of test requests - so this one
script uses a small pool of 5 concurrent requests to keep a weekly refresh
down to minutes instead of hours. Everything else in this project still
makes one request at a time. Separately, Boliga's *sold-search* endpoint
(unlike its regular search endpoint) turned out to have its own strict
rate limit - 5 requests per ~11 seconds, discovered by watching its
`X-RateLimit-*` response headers - so that part paces itself accordingly
and retries with a proper wait if it ever gets rate-limited anyway.
