"""
Hedonic pricing model: fits log(price) against a house's characteristics
using recent arm's-length sales as training data, then compares each
live listing's asking price to what the model would expect a house like
it to sell for.

    log(price) = b0 + b1*log(size) + b2*log(lotSize) + b3*buildYear
               + b4*energy_numeric + b5*log(distance_to_coast_m)
               + b6*postnummer_dummies

mispricing_pct = (udbudspris - modelpris) / modelpris

IMPORTANT: this is a filter for where to spend a Saturday, not a
valuation. A big negative mispricing_pct usually means the model is
missing something it can't see in Boliga's data - condition, sea view,
road noise, an awkward-shaped plot - not that a bargain was found. See
the README and the website for the same warning in more places.

Never rank on kr/m2 alone - see README for why that's a bad yardstick
for sommerhuse specifically (it ignores plot size and coast distance,
which move sommerhus prices more than almost anything else).
"""

import json
import math
import os

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yaml

from coastal_distance import distance_to_coast_m

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOLD_CACHE_PATH = os.path.join(BASE_DIR, "sold_cache.json")
AREAS_PATH = os.path.join(BASE_DIR, "areas.yaml")

MIN_COMPS_PER_POSTNUMMER = 50
MIN_R_SQUARED_WARNING = 0.6

# A = best, G = worst. Sommerhuse without a rating show up as "-" and get
# dropped from the training data (the model can't use a missing value).
ENERGY_CLASS_TO_NUMERIC = {
    "A2020": 1, "A2015": 1, "A2010": 1, "A": 1,
    "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7,
}
NEUTRAL_ENERGY_NUMERIC = 4  # "D", used when a sold comp has no energy label


def load_zipcode_to_area():
    with open(AREAS_PATH, "r", encoding="utf-8") as f:
        areas = yaml.safe_load(f)
    mapping = {}
    for area_key, info in areas.items():
        for zipcode in info.get("zipcodes", []):
            mapping[zipcode] = area_key
    return mapping


def load_sold_cache():
    if not os.path.exists(SOLD_CACHE_PATH):
        raise FileNotFoundError(
            "sold_cache.json not found - run sold_cache.py first to fetch "
            "sold-price comparables."
        )
    with open(SOLD_CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_training_frame(sold_records, zipcode_to_area):
    """Turns raw sold records into a clean dataframe ready for the
    regression, dropping anything missing a needed field, and deciding
    per-postnummer vs. per-area pooling for the dummy variable."""
    rows = []
    for r in sold_records:
        if r.get("saleType") != "Alm. Salg":
            continue
        size = r.get("size")
        lot_size = r.get("lotSize")
        build_year = r.get("buildYear")
        energy_class = r.get("energyClass")
        distance = r.get("distance_to_coast_m")
        price = r.get("price")

        if not size or not lot_size or not build_year or not price:
            continue
        if distance is None:
            continue

        # Energy label is missing for the vast majority of sold sommerhuse
        # (older, small secondary homes are often never rated) - requiring
        # it would throw away over 99% of the training data. Instead,
        # missing/unrecognised labels get a neutral mid-scale value plus a
        # separate "was it even rated" indicator, so the model can still
        # use every other bit of info about the house.
        normalized_energy = (energy_class or "").upper()
        energy_known = normalized_energy in ENERGY_CLASS_TO_NUMERIC
        energy_numeric = ENERGY_CLASS_TO_NUMERIC.get(normalized_energy, NEUTRAL_ENERGY_NUMERIC)

        rows.append({
            "zip_code": r["zipCode"],
            "area": zipcode_to_area.get(r["zipCode"], "unknown"),
            "price": price,
            "size": size,
            "lot_size": lot_size,
            "build_year": build_year,
            "energy_numeric": energy_numeric,
            "energy_known": energy_known,
            "distance_to_coast_m": max(distance, 1),  # avoid log(0)
            "address": r.get("address"),
            "sold_date": r.get("soldDate"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, {}

    # Decide the dummy-variable grouping per postnummer: use the
    # postnummer's own zip if it has enough comps, otherwise pool it with
    # its whole area so a thin postnummer still gets a usable estimate.
    counts = df["zip_code"].value_counts()
    pooled_zipcodes = set(counts[counts < MIN_COMPS_PER_POSTNUMMER].index)

    df["dummy_group"] = df.apply(
        lambda row: f"area_{row['area']}" if row["zip_code"] in pooled_zipcodes
        else f"zip_{row['zip_code']}",
        axis=1,
    )

    pooling_info = {
        zc: zipcode_to_area.get(zc, "unknown")
        for zc in pooled_zipcodes
    }
    return df, pooling_info


def fit_model(df):
    df = df.copy()
    df["log_price"] = np.log(df["price"])
    df["log_size"] = np.log(df["size"])
    df["log_lot_size"] = np.log(df["lot_size"])
    df["log_distance"] = np.log(df["distance_to_coast_m"])

    formula = (
        "log_price ~ log_size + log_lot_size + build_year + energy_numeric "
        "+ energy_known + log_distance + C(dummy_group)"
    )
    model = smf.ols(formula, data=df).fit()
    return model, df


def find_nearest_comps(training_df, dummy_group, latitude, longitude, n=5):
    """The n physically closest sold comparables within the same dummy
    group used for a listing's model price - for showing on the website
    ("measured against these 5 houses"), not for the regression itself."""
    subset = training_df[training_df["dummy_group"] == dummy_group]
    if subset.empty or latitude is None or longitude is None:
        return []

    # Flat-earth approximation is fine at this scale (a few km at most) -
    # good enough for "which comps are nearest", not used for scoring.
    lat_scale = 111_320  # metres per degree latitude
    lon_scale = 111_320 * math.cos(math.radians(latitude))

    def distance_m(row):
        dy = (row["latitude"] - latitude) * lat_scale
        dx = (row["longitude"] - longitude) * lon_scale
        return math.hypot(dx, dy)

    subset = subset.copy()
    subset["distance_m"] = subset.apply(distance_m, axis=1)
    nearest = subset.nsmallest(n, "distance_m")

    return [
        {
            "address": row["address"],
            "sold_date": row["sold_date"],
            "price": row["price"],
            "size": row["size"],
            "distance_km": round(row["distance_m"] / 1000, 1),
        }
        for _, row in nearest.iterrows()
    ]


def local_r_squared(model, df, mask):
    """R-squared restricted to just the rows where mask is True - lets us
    report how well the (pooled) model actually fits one specific
    postnummer's houses, not just the dataset as a whole."""
    subset = df[mask]
    if len(subset) < 2:
        return None
    actual = subset["log_price"]
    predicted = model.predict(subset)
    ss_res = ((actual - predicted) ** 2).sum()
    ss_tot = ((actual - actual.mean()) ** 2).sum()
    if ss_tot == 0:
        return None
    return 1 - ss_res / ss_tot


def print_model_report(model, df, pooling_info, zipcode_to_area):
    print(f"\nHedonic model fitted on {len(df)} arm's-length sold comparables.")
    print(f"Overall R-squared: {model.rsquared:.3f}")
    print(f"Observations: {model.nobs:.0f}\n")

    if pooling_info:
        print("Postnumre pooled with their area (fewer than "
              f"{MIN_COMPS_PER_POSTNUMMER} comps on their own):")
        for zc, area in sorted(pooling_info.items()):
            n = (df["zip_code"] == zc).sum()
            print(f"  {zc} -> pooled with {area} ({n} comps on its own)")
        print()

    print(f"{'Postnummer':<12}{'Comps':>8}{'Local R2':>12}")
    for zc in sorted(df["zip_code"].unique()):
        mask = df["zip_code"] == zc
        n = mask.sum()
        r2 = local_r_squared(model, df, mask)
        r2_str = f"{r2:.3f}" if r2 is not None else "n/a"
        warning = "  <-- below 0.6, residuals here aren't very meaningful" if (
            r2 is not None and r2 < MIN_R_SQUARED_WARNING
        ) else ""
        print(f"{zc:<12}{n:>8}{r2_str:>12}{warning}")


def predict_model_price(model, training_df, size, lot_size, build_year, energy_numeric, energy_known, distance_to_coast_m_, zip_code, area):
    """Predicts what the model expects a house like this to sell for. Uses
    the postnummer's own dummy group if it had enough training comps,
    otherwise falls back to the pooled area group - matching however that
    postnummer was actually trained."""
    zip_has_own_group = (training_df["zip_code"] == zip_code).any() and (
        training_df.loc[training_df["zip_code"] == zip_code, "dummy_group"].iloc[0]
        == f"zip_{zip_code}"
    )
    dummy_group = f"zip_{zip_code}" if zip_has_own_group else f"area_{area}"

    if dummy_group not in training_df["dummy_group"].unique():
        return None  # no comps at all for this postnummer or its area

    row = pd.DataFrame([{
        "log_size": math.log(size),
        "log_lot_size": math.log(lot_size),
        "build_year": build_year,
        "energy_numeric": energy_numeric,
        "energy_known": energy_known,
        "log_distance": math.log(max(distance_to_coast_m_, 1)),
        "dummy_group": dummy_group,
    }])
    log_price_pred = model.predict(row).iloc[0]
    return math.exp(log_price_pred)


if __name__ == "__main__":
    zipcode_to_area = load_zipcode_to_area()
    cache = load_sold_cache()
    df, pooling_info = build_training_frame(cache["records"], zipcode_to_area)

    if df.empty:
        print("No usable sold comparables yet (missing lot size/energy class/etc).")
    else:
        model, df = fit_model(df)
        print_model_report(model, df, pooling_info, zipcode_to_area)
