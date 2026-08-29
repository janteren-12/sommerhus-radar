"""
Seller-motivation sub-score (0-100): how much negotiating room a listing
probably has, based only on things scrape.py already tracks - how long
it's been for sale relative to similar houses, how much the price has
already been cut, how many separate times it was cut, whether it was
pulled off the market and relisted, and whether it was first listed in
the off-season (Oct-Feb), when sellers are more often motivated by a
life event than by testing the market.

Each signal is turned into a percentile rank within the current pool of
active listings (matching the same skew-resistant approach used for the
overall composite score - see composite.py), then combined with fixed
weights into one 0-100 number.
"""

from datetime import datetime, timedelta, timezone

MIN_ACTIVE_FOR_POSTNUMMER_STATS = 10

# Internal weights for the four motivation signals. A judgement call -
# liggetid and cumulative price cut are weighted highest since they're
# the most direct evidence of a seller under pressure; a relist or an
# off-season listing are treated as smaller, binary nudges rather than
# percentile-ranked, since "did this happen at all" matters more than
# "by how much".
WEIGHT_LIGGETID = 0.30
WEIGHT_PRISNEDSLAG = 0.30
WEIGHT_PRICE_CUT_COUNT = 0.15
WEIGHT_RELISTED = 0.15
WEIGHT_OFF_SEASON = 0.10

OFF_SEASON_MONTHS = {10, 11, 12, 1, 2}


def percentile_rank(values, value):
    """Fraction of values that are <= value. 1.0 means "highest in the
    pool", 0.0 means "lowest". Ties are handled by average rank."""
    if not values:
        return 0.5
    sorted_values = sorted(values)
    n = len(sorted_values)
    # Count strictly-less and equal-to, average the two ranks (handles ties
    # the same way as pandas' default percentile rank).
    less = sum(1 for v in sorted_values if v < value)
    less_or_equal = sum(1 for v in sorted_values if v <= value)
    return (less + less_or_equal) / (2 * n)


def estimate_originally_listed_month(listing):
    """Which month a listing was actually first put up for sale.

    Deliberately NOT based on first_seen: that only records when this
    tool first noticed the listing, which is wrong the moment a new area
    is added, or for any listing this tool simply hadn't gotten around to
    yet - a house for sale for a year would wrongly look freshly listed
    today. Boliga's own dage_paa_markedet (days for sale) counts from the
    real listing date regardless of when we started watching, so we work
    backwards from that instead. Falls back to first_seen's month only if
    dage_paa_markedet is missing.
    """
    days_on_market = listing.get("dage_paa_markedet")
    if days_on_market is not None:
        estimated_date = datetime.now(timezone.utc) - timedelta(days=days_on_market)
        return estimated_date.month

    if listing.get("first_seen"):
        return int(listing["first_seen"][5:7])
    return None


def group_key_for_stats(listing, postnummer_counts):
    """Which group's liggetid distribution to compare a listing against:
    its own postnummer if there are enough other active listings there,
    otherwise its whole area."""
    postnummer = listing["postnummer"]
    if postnummer_counts.get(postnummer, 0) >= MIN_ACTIVE_FOR_POSTNUMMER_STATS:
        return ("postnummer", postnummer)
    return ("area", listing["area"])


def compute_motivation_scores(active_listings):
    """Returns {listing_id: motivation_score} for every listing in
    active_listings (0-100 each)."""
    postnummer_counts = {}
    for l in active_listings:
        postnummer_counts[l["postnummer"]] = postnummer_counts.get(l["postnummer"], 0) + 1

    # Group listings' liggetid and cumulative price-cut% by comparison
    # group, so percentile rank is computed against the right peer set.
    liggetid_by_group = {}
    prisnedslag_by_group = {}
    cut_count_by_group = {}

    for l in active_listings:
        key = group_key_for_stats(l, postnummer_counts)
        liggetid_by_group.setdefault(key, []).append(l.get("dage_paa_markedet") or 0)
        prisnedslag = -l["prisaendring_pct"] if l.get("prisaendring_pct") and l["prisaendring_pct"] < 0 else 0
        prisnedslag_by_group.setdefault(key, []).append(prisnedslag)
        cut_count_by_group.setdefault(key, []).append(l.get("price_cut_count") or 0)

    scores = {}
    for l in active_listings:
        key = group_key_for_stats(l, postnummer_counts)

        liggetid = l.get("dage_paa_markedet") or 0
        liggetid_pct = percentile_rank(liggetid_by_group[key], liggetid)

        prisnedslag = -l["prisaendring_pct"] if l.get("prisaendring_pct") and l["prisaendring_pct"] < 0 else 0
        prisnedslag_pct = percentile_rank(prisnedslag_by_group[key], prisnedslag)

        cut_count = l.get("price_cut_count") or 0
        cut_count_pct = percentile_rank(cut_count_by_group[key], cut_count)

        relisted_signal = 1.0 if l.get("was_relisted") else 0.0

        off_season_signal = 1.0 if estimate_originally_listed_month(l) in OFF_SEASON_MONTHS else 0.0

        raw_score = (
            WEIGHT_LIGGETID * liggetid_pct
            + WEIGHT_PRISNEDSLAG * prisnedslag_pct
            + WEIGHT_PRICE_CUT_COUNT * cut_count_pct
            + WEIGHT_RELISTED * relisted_signal
            + WEIGHT_OFF_SEASON * off_season_signal
        )

        scores[l["id"]] = {
            "score": round(raw_score * 100, 1),
            "liggetid_dage": liggetid,
            "liggetid_percentile": round(liggetid_pct * 100),
            "prisnedslag_pct": round(prisnedslag, 1),
            "price_cut_count": cut_count,
            "was_relisted": bool(l.get("was_relisted")),
            "off_season_listing": bool(off_season_signal),
            "compared_against": f"{key[0]}: {key[1]}",
        }

    return scores
