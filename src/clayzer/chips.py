"""Chips: 512 × 512 px RGB windows of NAIP at 0.6 m (caption-plan.md §3, §5.3).

Planetary Computer's STAC catalog finds the NAIP image. Pixels come from one of two copies of
the same imagery (CLAYZER_NAIP_SOURCE):
- `pc`: Planetary Computer (free; signed with a short-lived SAS token), for preparation.
- `aws`: the `naip-visualization` bucket in us-west-2 (Requester-Pays), in the sandbox
  account. Falls back to `pc` when an image isn't in the bucket.

Positions inside a Chip are pixel coordinates, column right and row down, north up.
"""

import io
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date

import numpy as np
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from clayzer.config import ca_bundle
from clayzer.grid import cell_at

SIZE = 512
RES = 0.6
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
# Slack around a Chip's footprint when checking a NAIP item covers it, for the approximate
# metres-to-degrees conversion.
FOOTPRINT_MARGIN_M = 20.0
# A Chip with more blank (all-zero) pixels than this is refused: it crossed a tile's edge.
MAX_BLANK = 0.001


@dataclass(frozen=True)
class Chip:
    id: str
    date: str
    bbox: tuple[float, float, float, float]  # lon/lat: west, south, east, north
    crs: str
    left: float  # Chip's north-west corner in `crs` metres
    top: float
    source: str
    naip_item: str
    size: int = SIZE
    res: float = RES
    # How far the Chip's centre was moved from the point it was cut around, in metres (east,
    # north), so a positive's site isn't always in the centre cell.
    offset_m: tuple[float, float] = (0.0, 0.0)

    @property
    def png(self) -> str:
        return f"{self.id}.png"

    def to_crs(self, lons, lats):
        from rasterio.warp import transform

        return transform("EPSG:4326", self.crs, list(lons), list(lats))

    def pixel(self, lon: float, lat: float) -> tuple[float, float]:
        (x,), (y,) = self.to_crs([lon], [lat])
        return (x - self.left) / self.res, (self.top - y) / self.res

    def inside(self, lon: float, lat: float) -> bool:
        col, row = self.pixel(lon, lat)
        return 0 <= col < self.size and 0 <= row < self.size

    def cell(self, lon: float, lat: float) -> str:
        return cell_at(*self.pixel(lon, lat), self.size)

    def to_pixels(self, geom: BaseGeometry) -> BaseGeometry:
        """A lon/lat geometry in Chip pixel coordinates."""

        def f(lons, lats, _z=None):
            xs, ys = self.to_crs(lons, lats)
            return (
                [(x - self.left) / self.res for x in xs],
                [(self.top - y) / self.res for y in ys],
            )

        return shapely_transform(f, geom)

    def save(self, store) -> None:
        store.put(
            f"chips/{self.id}.json",
            (json.dumps(asdict(self), indent=2) + "\n").encode(),
            "application/json",
        )

    @classmethod
    def load(cls, store, chip_id: str) -> "Chip":
        d = json.loads(store.get(f"chips/{chip_id}.json"))
        d["bbox"] = tuple(d["bbox"])
        d["offset_m"] = tuple(d.get("offset_m", (0.0, 0.0)))
        return cls(**d)


def chip_footprint(lon: float, lat: float, offset_m: tuple[float, float] = (0.0, 0.0)):
    """The lon/lat box a Chip around (lon, lat), moved by `offset_m`, will cover, with a margin."""
    from shapely.geometry import box

    half = SIZE * RES / 2 + FOOTPRINT_MARGIN_M
    m_lat, m_lon = 111_320.0, 111_320.0 * math.cos(math.radians(lat))
    cx, cy = lon + offset_m[0] / m_lon, lat + offset_m[1] / m_lat
    return box(cx - half / m_lon, cy - half / m_lat, cx + half / m_lon, cy + half / m_lat)


def find_naip(
    lon: float,
    lat: float,
    after_year: int | None = None,
    offset_m: tuple[float, float] = (0.0, 0.0),
    before_year: int | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
):
    """The latest NAIP item that covers the whole Chip around a point, captured after
    `after_year` and before `before_year` if given (a Change Case's earlier Chip predates the
    site). `after_date` and `before_date` (ISO, inclusive) bound it to the day instead, for a
    construction quarter from GRW.

    NAIP comes in tiles; a Chip that crosses a tile's edge would be read partly blank (seen
    2026-11-04 on 7 of 63 Chips). So the item must cover the Chip's whole footprint, not just
    the point; an older item that does is better than a newer one that doesn't.
    """
    import planetary_computer
    import pystac_client

    catalog = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    start = after_date or (f"{after_year + 1}-01-01" if after_year else "2010-01-01")
    end = before_date or (f"{before_year - 1}-12-31" if before_year else date.today().isoformat())
    footprint = chip_footprint(lon, lat, offset_m)
    items = catalog.search(
        collections=["naip"],
        intersects=footprint.__geo_interface__,
        datetime=f"{start}/{end}",
    ).items()
    item = covering_item(list(items), footprint)
    if item is None:
        raise LookupError(
            f"no NAIP item from {start} to {end} covers the whole Chip at ({lon}, {lat})"
        )
    return item


def covering_item(items: list, footprint):
    """The newest item whose footprint contains the Chip's, or None."""
    from shapely.geometry import shape

    for item in sorted(items, key=lambda i: i.datetime, reverse=True):
        if shape(item.geometry).contains(footprint):
            return item
    return None


# https://naipeuwest.blob.core.windows.net/naip/v002/ca/2022/ca_060cm_2022/35118/m_....tif
_PC_HREF = re.compile(r"/v002/(\w+)/(\d{4})/\w+_0*(\d+)cm_\d{4}/(\d+)/([^/?]+\.tif)")
AWS_NAIP_BUCKET = "naip-visualization"


def aws_key(pc_href: str) -> str | None:
    """The `naip-visualization` key for a Planetary Computer NAIP href, if it follows the
    usual layout (state/year/resolution/rgb/quad/file)."""
    m = _PC_HREF.search(pc_href)
    if not m:
        return None
    state, year, res, quad, name = m.groups()
    return f"{state}/{year}/{res}cm/rgb/{quad}/{name}"


def _source(item, naip_source: str) -> tuple[str, str, dict]:
    """(GDAL path, Chip source label, GDAL options) for reading the item's pixels."""
    href = item.assets["image"].href
    if naip_source == "aws":
        key = aws_key(href)
        if key:
            import boto3
            from botocore.exceptions import ClientError

            try:
                boto3.client("s3", region_name="us-west-2").head_object(
                    Bucket=AWS_NAIP_BUCKET, Key=key, RequestPayer="requester"
                )
                opts = {"AWS_REQUEST_PAYER": "requester", "AWS_REGION": "us-west-2"}
                return f"/vsis3/{AWS_NAIP_BUCKET}/{key}", "naip-aws", opts
            except ClientError:
                pass
    return href, "naip-pc", {}


# A positive's point stays at least this far inside the Chip's edge after offsetting.
OFFSET_MARGIN_M = 50.0


def offset_for(seed: str) -> tuple[float, float]:
    """A repeatable offset (east, north) in metres that puts the Chip's point in a random cell.

    Positives are cut around their USGS point; without an offset the site is always in the
    centre cell, so "solar array, centre" is right by construction and position measures
    nothing (seen 2026-11-04). Each of the 9 cells is equally likely, and the point stays at
    least OFFSET_MARGIN_M inside the Chip's edge.
    """
    import random

    rng = random.Random(seed)
    third, margin = SIZE / 3, OFFSET_MARGIN_M / RES
    col_cell, row_cell = rng.randrange(3), rng.randrange(3)
    col = rng.uniform(max(col_cell * third, margin), min((col_cell + 1) * third, SIZE - margin))
    row = rng.uniform(max(row_cell * third, margin), min((row_cell + 1) * third, SIZE - margin))
    # The point sits at (col, row); the Chip's centre moves the opposite way.
    east, north = (col - SIZE / 2) * RES, (SIZE / 2 - row) * RES
    return round(-east, 1), round(-north, 1)


def blank_share(rgb) -> float:
    """The share of a (3, H, W) image's pixels that are blank: zero in every band."""
    return float((rgb.max(axis=0) == 0).mean())


def cut_chip(
    item,
    lon: float,
    lat: float,
    chip_id_prefix: str,
    store,
    naip_source: str = "pc",
    offset_m: tuple[float, float] = (0.0, 0.0),
):
    """Cut a Chip around (lon, lat) from a NAIP item, its centre moved by `offset_m` (east,
    north); store `chips/<id>.png` and `.json`."""
    import rasterio
    from PIL import Image
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import from_bounds

    day = item.datetime.strftime("%Y%m%d")
    chip_id = f"{chip_id_prefix}-{day}"
    half = SIZE * RES / 2
    path, source, opts = _source(item, naip_source)
    if ca_bundle():
        opts["GDAL_CURL_CA_BUNDLE"] = ca_bundle()
    with rasterio.Env(**opts), rasterio.open(path) as ds:
        (px,), (py,) = transform("EPSG:4326", ds.crs, [lon], [lat])
        cx, cy = px + offset_m[0], py + offset_m[1]
        left, top = cx - half, cy + half
        window = from_bounds(left, cy - half, cx + half, top, ds.transform)
        rgb = ds.read([1, 2, 3], window=window, out_shape=(3, SIZE, SIZE), boundless=True)
        crs = ds.crs.to_string()
        bbox = transform_bounds(ds.crs, "EPSG:4326", left, cy - half, cx + half, top)
    blank = blank_share(rgb)
    if blank > MAX_BLANK:
        raise ValueError(f"the Chip is {blank:.0%} blank: it crosses the edge of {item.id}")

    png = io.BytesIO()
    Image.fromarray(np.moveaxis(rgb, 0, -1)).save(png, format="PNG")
    store.put(f"chips/{chip_id}.png", png.getvalue(), "image/png")
    chip = Chip(
        id=chip_id,
        date=item.datetime.date().isoformat(),
        bbox=tuple(round(v, 6) for v in bbox),
        crs=crs,
        left=left,
        top=top,
        source=source,
        naip_item=item.id,
        offset_m=offset_m,
    )
    chip.save(store)
    return chip
