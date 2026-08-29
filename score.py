"""
The scoring pipeline: reads the current for-sale listings (docs/data.json,
kept fresh by scrape.py) plus the cached sold-price comparables
(sold_cache.json, kept fresh weekly by sold_cache.py), and adds a deal
score to every active listing.

This is deliberately a separate script from scrape.py, run right after it:
if fitting the pricing model or computing yields breaks for any reason,
the for-sale listings themselves should still get published rather than
the whole site going stale.

IMPORTANT: the score is a filter for where to spend a Saturday, not a
valuation. A big negative mispricing_pct usually means the hedonic model
is missing something it has no way to see - condition, sea view, road
noise, an awkwardly shaped plot - not that a bargain was found. This is
shown on the website itself, not just here.

Run it with:
    python score.py
"""

import json
import os

import yaml

from coastal_distance import distance_to_coast_m
from composite import apply_veto_flags, compute_composite_scores
from mispricing import (
    build_training_frame,
    find_nearest_comps,
    fit_model,
    load_sold_cache,
    load_zipcode_to_area,
    predict_model_price,
    print_model_report,
    ENERGY_CLASS_TO_NUMERIC,
    NEUTRAL_ENERGY_NUMERIC,
)
from yield_calc import calculate_net_yield

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "docs", "data.json")
RENTAL_BENCHMARKS_PATH = os.path.join(BASE_DIR, "rental_benchmarks.yaml")
FLAGS_PATH = os.path.join(BASE_DIR, "flags.yaml")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def compute_mispricing_for_listing(listing, model, training_df):
    lat, lon = listing.get("latitude"), listing.get("longitude")
    if not all([listing.get("m2"), listing.get("grund_m2"), listing.get("byggeaar"), lat, lon]):
        return None

    # Same neutral-impute treatment as the training data: most listings
    # (sold or for-sale) simply have no registered energy label at all.
    energy_class = (listing.get("energimaerke") or "").upper()
    energy_known = energy_class in ENERGY_CLASS_TO_NUMERIC
    energy_numeric = ENERGY_CLASS_TO_NUMERIC.get(energy_class, NEUTRAL_ENERGY_NUMERIC)

    distance = distance_to_coast_m(lat, lon)
    modelpris = predict_model_price(
        model, training_df,
        size=listing["m2"],
        lot_size=listing["grund_m2"],
        build_year=listing["byggeaar"],
        energy_numeric=energy_numeric,
        energy_known=energy_known,
        distance_to_coast_m_=distance,
        zip_code=listing["postnummer"],
        area=listing["area"],
    )
    if modelpris is None:
        return None

    mispricing_pct = (listing["price"] - modelpris) / modelpris

    zip_has_own_group = (training_df["zip_code"] == listing["postnummer"]).any() and (
        training_df.loc[training_df["zip_code"] == listing["postnummer"], "dummy_group"].iloc[0]
        == f"zip_{listing['postnummer']}"
    )
    dummy_group = f"zip_{listing['postnummer']}" if zip_has_own_group else f"area_{listing['area']}"
    comps = find_nearest_comps(training_df, dummy_group, lat, lon, n=5)

    return {
        "distance_to_coast_m": round(distance),
        "modelpris": round(modelpris),
        "mispricing_pct": round(mispricing_pct * 100, 1),
        "pooled_with_area": not zip_has_own_group,
        "comparables": comps,
    }


def compute_yield_for_listing(listing, rental_benchmarks, config):
    area = listing.get("area")
    benchmark = rental_benchmarks.get(area, {})
    high = benchmark.get("high_season_week_price")
    low = benchmark.get("low_season_week_price")
    if high is None or low is None:
        return None

    result = calculate_net_yield(
        price=listing["price"],
        weeks_rented=benchmark.get("weeks_rented_per_year", 18),
        high_season_weeks=benchmark.get("high_season_weeks", 8),
        high_season_week_price=high,
        low_season_week_price=low,
        config=config,
    )
    result["nettoafkast_pct"] = round(result["nettoafkast"] * 100, 2)
    return result


def build_reason_line(listing, mispricing, net_yield, motivation_detail):
    parts = []
    if mispricing:
        parts.append(f"{abs(mispricing['mispricing_pct']):.0f}% "
                     f"{'under' if mispricing['mispricing_pct'] < 0 else 'over'} modelpris")
    if listing.get("dage_paa_markedet") is not None:
        parts.append(f"{listing['dage_paa_markedet']} dage på markedet")
    if motivation_detail and motivation_detail.get("price_cut_count"):
        n = motivation_detail["price_cut_count"]
        parts.append(f"{n} prisnedslag" if n != 1 else "1 prisnedslag")
    if net_yield:
        parts.append(f"{net_yield['nettoafkast_pct']:.1f}% afkast")
    return ", ".join(parts) if parts else "Ikke nok data til en begrundelse endnu"


def main():
    if not os.path.exists(DATA_PATH):
        print("docs/data.json not found - run scrape.py first.")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    config = load_yaml(CONFIG_PATH)
    rental_benchmarks = load_yaml(RENTAL_BENCHMARKS_PATH)
    flags_by_id = load_yaml(FLAGS_PATH)

    active_listings = [l for l in data["listings"] if not l["sold_or_removed"]]
    inactive_listings = [l for l in data["listings"] if l["sold_or_removed"]]

    try:
        zipcode_to_area = load_zipcode_to_area()
        cache = load_sold_cache()
        training_df, pooling_info = build_training_frame(cache["records"], zipcode_to_area)
        if training_df.empty:
            raise ValueError("No usable sold comparables in sold_cache.json yet.")
        model, training_df = fit_model(training_df)
        print_model_report(model, training_df, pooling_info, zipcode_to_area)
    except (FileNotFoundError, ValueError) as error:
        print(f"Mispricing model unavailable: {error}")
        model, training_df = None, None

    mispricing_by_listing_id = {}
    yield_by_listing_id = {}

    for listing in active_listings:
        mispricing = None
        if model is not None:
            mispricing = compute_mispricing_for_listing(listing, model, training_df)
        listing["mispricing"] = mispricing
        mispricing_by_listing_id[listing["id"]] = (
            mispricing["mispricing_pct"] if mispricing else None
        )

        net_yield = compute_yield_for_listing(listing, rental_benchmarks, config)
        listing["nettoafkast"] = net_yield
        yield_by_listing_id[listing["id"]] = (
            net_yield["nettoafkast_pct"] if net_yield else None
        )

    rankable, flagged = apply_veto_flags(active_listings, flags_by_id)

    weights = (config.get("score_weights") or {})
    weights = {
        "mispricing": weights.get("mispricing", 0.40),
        "nettoafkast": weights.get("nettoafkast", 0.30),
        "motivation": weights.get("motivation", 0.20),
        "kvalitet": weights.get("kvalitet", 0.10),
    }

    composite_scores = compute_composite_scores(
        rankable, mispricing_by_listing_id, yield_by_listing_id, weights
    )

    for listing in rankable:
        breakdown = composite_scores[listing["id"]]
        listing["score"] = breakdown["score"]
        listing["score_breakdown"] = breakdown
        listing["reason"] = build_reason_line(
            listing, listing["mispricing"], listing["nettoafkast"], breakdown["motivation_detail"]
        )

    for listing in flagged:
        listing["score"] = None
        listing["score_breakdown"] = None
        listing["reason"] = "Udelukket fra rangering: " + ", ".join(listing.get("flags", []))

    data["listings"] = rankable + flagged + inactive_listings
    data["scoring_last_updated"] = data.get("last_updated")

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    scored_count = sum(1 for l in rankable if l["score"] is not None)
    print(f"\nScored {scored_count} listings, {len(flagged)} excluded by veto flags.")
    print(f"Written back to {DATA_PATH}")


if __name__ == "__main__":
    main()
