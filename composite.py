"""
Combines the three deal scores (mispricing, net yield, seller motivation)
plus a quality signal into one 0-100 composite score.

Each component is turned into a PERCENTILE RANK within the current pool
of active, non-flagged listings before being combined - not a z-score.
Sommerhus prices (and yields) are heavily right-skewed by a handful of
very expensive liebhaverhuse, and a z-score would let those few houses
distort everyone else's score. Percentile rank doesn't have that problem.

Weights (see config.yaml to change them):
    Mispricing           40%
    Nettoafkast          30%
    Sælgers motivation   20%
    Kvalitet             10%

A component that couldn't be computed for a given listing (no sold
comparables yet, or rental_benchmarks.yaml not filled in for its area)
contributes a neutral 50th-percentile score rather than being guessed at,
and the website says so on that listing's card.
"""

from motivation import percentile_rank

# Danish energy labels, best to worst. Missing/unknown energy class is
# treated as neutral (middle of the scale) rather than punishing a
# listing just because the label wasn't registered.
ENERGY_CLASS_TO_NUMERIC = {
    "A2020": 1, "A2015": 1, "A2010": 1, "A": 1,
    "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7,
}
NEUTRAL_ENERGY_NUMERIC = 4  # "D", roughly the middle of the scale

DEFAULT_WEIGHTS = {
    "mispricing": 0.40,
    "nettoafkast": 0.30,
    "motivation": 0.20,
    "kvalitet": 0.10,
}


def _percentile_component(values_by_id, invert=False):
    """values_by_id: {listing_id: value or None}. Returns
    {listing_id: percentile 0-1}, with None values getting a neutral 0.5."""
    available = [v for v in values_by_id.values() if v is not None]
    result = {}
    for listing_id, value in values_by_id.items():
        if value is None:
            result[listing_id] = 0.5
            continue
        pct = percentile_rank(available, value)
        result[listing_id] = (1 - pct) if invert else pct
    return result


def compute_quality_scores(active_listings):
    """Byggeår (newer = better) and energimærke (better label = better),
    each weighted equally within "Kvalitet". Boliga has no renovation-year
    field for these listings, so that part of the original three-factor
    idea (byggeår, energimærke, renoveringsår) isn't included - see
    README for why, rather than estimating a number that isn't there."""
    byggeaar_by_id = {l["id"]: l.get("byggeaar") for l in active_listings}
    energy_by_id = {}
    for l in active_listings:
        energy_class = l.get("energimaerke")
        energy_by_id[l["id"]] = ENERGY_CLASS_TO_NUMERIC.get(energy_class)

    byggeaar_pct = _percentile_component(byggeaar_by_id)  # newer = higher percentile = better
    energy_pct = _percentile_component(energy_by_id, invert=True)  # low numeric = better, so invert

    quality = {}
    for l in active_listings:
        listing_id = l["id"]
        quality[listing_id] = (byggeaar_pct[listing_id] + energy_pct[listing_id]) / 2
    return quality


def apply_veto_flags(active_listings, flags_by_id):
    """Splits listings into (rankable, flagged). A listing is flagged if
    any manual flag is true, or if it has a poor energy label with
    electric heating (auto-detected - see flags.yaml for why)."""
    rankable, flagged = [], []
    for l in active_listings:
        manual_flags = flags_by_id.get(l["id"], {})
        auto_flag = ENERGY_CLASS_TO_NUMERIC.get(l.get("energimaerke"), 0) >= 5  # E, F, G
        # Manual override: if the user explicitly set this flag to false,
        # respect that even though the energy label looks poor.
        if "elvarme_daarligt_energimaerke" in manual_flags:
            auto_flag = manual_flags["elvarme_daarligt_energimaerke"]

        active_flag_names = [k for k, v in manual_flags.items() if v and k != "elvarme_daarligt_energimaerke"]
        if auto_flag:
            active_flag_names.append("elvarme_daarligt_energimaerke")

        if active_flag_names:
            l["flags"] = active_flag_names
            flagged.append(l)
        else:
            rankable.append(l)

    return rankable, flagged


def compute_composite_scores(rankable_listings, mispricing_by_id, yield_by_id, weights=None):
    weights = weights or DEFAULT_WEIGHTS

    from motivation import compute_motivation_scores
    motivation_details = compute_motivation_scores(rankable_listings)
    motivation_raw = {lid: details["score"] for lid, details in motivation_details.items()}

    mispricing_pct_component = _percentile_component(mispricing_by_id, invert=True)  # cheaper than model = higher score
    yield_pct_component = _percentile_component(yield_by_id)  # higher yield = higher score
    motivation_pct_component = _percentile_component(motivation_raw)  # re-percentile the 0-100 sub-score itself
    quality_pct_component = compute_quality_scores(rankable_listings)

    scores = {}
    for l in rankable_listings:
        listing_id = l["id"]
        composite = (
            weights["mispricing"] * mispricing_pct_component[listing_id]
            + weights["nettoafkast"] * yield_pct_component[listing_id]
            + weights["motivation"] * motivation_pct_component[listing_id]
            + weights["kvalitet"] * quality_pct_component[listing_id]
        ) * 100

        scores[listing_id] = {
            "score": round(composite, 1),
            "weights": weights,
            "mispricing_percentile": round(mispricing_pct_component[listing_id] * 100),
            "nettoafkast_percentile": round(yield_pct_component[listing_id] * 100),
            "motivation_percentile": round(motivation_pct_component[listing_id] * 100),
            "kvalitet_percentile": round(quality_pct_component[listing_id] * 100),
            "motivation_detail": motivation_details[listing_id],
            "mispricing_available": mispricing_by_id.get(listing_id) is not None,
            "nettoafkast_available": yield_by_id.get(listing_id) is not None,
        }

    return scores
