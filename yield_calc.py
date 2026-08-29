"""
Net rental yield (nettoafkast) for a sommerhus, under Denmark's 2026
skematiske-metode rules for renting out through a bureau.

This is a standalone function on purpose - calculate_net_yield() takes
plain numbers in and returns plain numbers out, so it can be called from
the main scoring pipeline, tested on its own, or used from a Python
console to sanity-check a specific house by hand.

IMPORTANT CAVEATS (also in the README):
- Ejendomsværdiskat is charged for the whole year under the skematiske
  metode, even for the weeks the house was rented out - it is not
  reduced for rental weeks.
- Whether "bruttolejeindtaegt" should be the bureau's gross booking price
  or what actually gets paid out to you (after cleaning fees, damage
  deposits, etc. depending on how the bureau invoices) affects the tax
  base. Confirm with a revisor which figure your specific bureau reports
  to SKAT before trusting this for real tax planning.
- There's no real "building value" figure available in this project's
  data (Boliga's public-valuation field is always empty for these
  listings), so the maintenance reserve is calculated against the asking
  price itself instead. That will overstate maintenance cost for an
  expensive plot with a modest house on it, and understate it the other
  way around.
"""


def calculate_net_yield(
    price,
    weeks_rented,
    high_season_weeks,
    high_season_week_price,
    low_season_week_price,
    config,
    show_work=False,
):
    """Returns a dict with every line item plus the final nettoafkast
    (as a ratio - multiply by 100 for a percentage). Set show_work=True to
    also print the full arithmetic, line by line."""
    cfg = config["yield_calculation"]

    low_season_weeks = max(0, weeks_rented - high_season_weeks)
    bruttolejeindtaegt = (
        high_season_weeks * high_season_week_price
        + low_season_weeks * low_season_week_price
    )

    efter_provision = bruttolejeindtaegt * (1 - cfg["commission"])

    driftsomkostninger = (
        cfg["grundskyld"]
        + cfg["ejendomsvaerdiskat"]
        + cfg["forsikring"]
        + cfg["grundejerforening"]
        + cfg["forbrug"]
    )

    vedligehold = price * cfg["vedligehold_pct_of_price"]

    bundfradrag = cfg["bundfradrag_privat"] if cfg["renting_privately"] else cfg["bundfradrag_via_bureau"]
    skattepligtig_del = max(0, bruttolejeindtaegt - bundfradrag) * 0.60
    skat = skattepligtig_del * cfg["kapitalindkomst_sats"]

    handelsomkostninger = cfg["handelsomkostninger_flat"]
    denominator = price + handelsomkostninger

    nettoresultat = efter_provision - driftsomkostninger - vedligehold - skat
    nettoafkast = nettoresultat / denominator if denominator else 0.0

    result = {
        "bruttolejeindtaegt": bruttolejeindtaegt,
        "efter_provision": efter_provision,
        "driftsomkostninger": driftsomkostninger,
        "vedligehold": vedligehold,
        "skat": skat,
        "nettoresultat": nettoresultat,
        "handelsomkostninger": handelsomkostninger,
        "koebspris_plus_handelsomkostninger": denominator,
        "nettoafkast": nettoafkast,
    }

    if show_work:
        print(f"Højsæson:  {high_season_weeks} uger × {high_season_week_price:,.0f} kr = {high_season_weeks * high_season_week_price:,.0f} kr")
        print(f"Lavsæson:  {low_season_weeks} uger × {low_season_week_price:,.0f} kr = {low_season_weeks * low_season_week_price:,.0f} kr")
        print(f"Bruttolejeindtægt                         = {bruttolejeindtaegt:,.0f} kr")
        print(f"Efter provision ({cfg['commission']*100:.0f}%)                  = {efter_provision:,.0f} kr")
        print()
        print(f"Grundskyld                                = {cfg['grundskyld']:,.0f} kr")
        print(f"Ejendomsværdiskat                         = {cfg['ejendomsvaerdiskat']:,.0f} kr")
        print(f"Forsikring                                 = {cfg['forsikring']:,.0f} kr")
        print(f"Grundejerforening                          = {cfg['grundejerforening']:,.0f} kr")
        print(f"Forbrug                                    = {cfg['forbrug']:,.0f} kr")
        print(f"Driftsomkostninger i alt                   = {driftsomkostninger:,.0f} kr")
        print()
        print(f"Vedligehold ({cfg['vedligehold_pct_of_price']*100:.2f}% af {price:,.0f} kr)   = {vedligehold:,.0f} kr")
        print()
        print(f"Bundfradrag ({'privat' if cfg['renting_privately'] else 'via bureau'})              = {bundfradrag:,.0f} kr")
        print(f"Beløb over bundfradrag                     = {max(0, bruttolejeindtaegt - bundfradrag):,.0f} kr")
        print(f"  × 60% (kapitalindkomst-andel)            = {skattepligtig_del:,.0f} kr")
        print(f"  × {cfg['kapitalindkomst_sats']*100:.0f}% (kapitalindkomstskattesats)          = {skat:,.0f} kr skat")
        print()
        print(f"Nettoresultat = {efter_provision:,.0f} - {driftsomkostninger:,.0f} - {vedligehold:,.0f} - {skat:,.0f}")
        print(f"              = {nettoresultat:,.0f} kr")
        print()
        print(f"Købspris + handelsomkostninger ({handelsomkostninger:,.0f} kr) = {denominator:,.0f} kr")
        print(f"Nettoafkast = {nettoresultat:,.0f} / {denominator:,.0f} = {nettoafkast*100:.2f}%")

    return result


if __name__ == "__main__":
    import json
    import os

    import yaml

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(BASE_DIR, "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    with open(os.path.join(BASE_DIR, "docs", "data.json"), "r", encoding="utf-8") as f:
        data = json.load(f)

    listing = next(l for l in data["listings"] if l["area"] == "blaavand" and not l["sold_or_removed"])

    print(f"Eksempel: {listing['address']}, {listing['postnummer']} {listing['city']} - {listing['price']:,.0f} kr")
    print(
        "Rental-priserne herunder er IKKE udfyldt i rental_benchmarks.yaml endnu "
        "(de er null, som beskrevet i den fil) - dette er illustrative tal, kun "
        "for at vise regnestykket. Udfyld rental_benchmarks.yaml med rigtige tal "
        "for at få et reelt afkast for dine områder."
    )
    print()

    calculate_net_yield(
        price=listing["price"],
        weeks_rented=18,
        high_season_weeks=8,
        high_season_week_price=12000,   # illustrative only - see note above
        low_season_week_price=4000,     # illustrative only - see note above
        config=config,
        show_work=True,
    )
