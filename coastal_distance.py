"""
Straight-line distance from a point to the nearest bit of Danish coastline.

Coastline shape comes from Natural Earth's public-domain 10m coastline
dataset (downloaded once, clipped down to just the Denmark area, and
committed to the repo as data/coastline_denmark.geojson - see
data/README.md for where it came from).

Distances are computed in EPSG:25832 (ETRS89 / UTM zone 32N), the standard
metric map projection for Denmark, so "metres" actually means metres and
isn't distorted by using raw latitude/longitude degrees.
"""

import json
import os

from pyproj import Transformer
from shapely.geometry import MultiLineString, Point
from shapely.ops import transform

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COASTLINE_PATH = os.path.join(BASE_DIR, "data", "coastline_denmark.geojson")

_to_utm32n = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True).transform

_coastline_projected = None  # loaded lazily, once per process


def _load_coastline_projected():
    with open(COASTLINE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = [feature["geometry"]["coordinates"] for feature in data["features"]]
    coastline = MultiLineString(lines)
    return transform(_to_utm32n, coastline)


def distance_to_coast_m(latitude, longitude):
    """Straight-line distance in metres from (latitude, longitude) to the
    nearest point on the Danish coastline."""
    global _coastline_projected
    if _coastline_projected is None:
        _coastline_projected = _load_coastline_projected()

    x, y = _to_utm32n(longitude, latitude)
    point = Point(x, y)
    return _coastline_projected.distance(point)


if __name__ == "__main__":
    # A few sanity checks: Blåvand should be right on the coast, Herning
    # (well inland) should be tens of kilometres away.
    checks = {
        "Blåvand (Nordkrogen 5)": (55.5951, 8.1194),
        "Bornholm (Nexø)": (54.9935, 15.07939),
        "Herning (well inland)": (56.1333, 8.9833),
        "Copenhagen (coastal city)": (55.6761, 12.5683),
    }
    for name, (lat, lon) in checks.items():
        d = distance_to_coast_m(lat, lon)
        print(f"{name}: {d:,.0f} m")
