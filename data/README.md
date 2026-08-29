# data/

`coastline_denmark.geojson` - the Danish coastline, used by `coastal_distance.py`
to compute how far each listing is from the sea (a major driver of sommerhus
prices).

Source: [Natural Earth](https://www.naturalearthdata.com/), 10m resolution
coastline, public domain. Downloaded once from the
[nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector)
GitHub mirror (the official Natural Earth site only serves shapefiles, which
need conversion tools to read directly), then clipped down to just the area
around Denmark (roughly 7-16°E, 54.3-58.2°N) so the repo doesn't carry a
10MB global file for a few hundred kilometres of it. See
`clip_coastline.py`-style logic if you ever need to regenerate this (not
included as a script here since it's a one-off - re-download the global file
from the mirror above and filter features whose bounding box overlaps
Denmark).
