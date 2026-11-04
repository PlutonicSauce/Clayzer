"""Global Renewables Watch v1.0 (Microsoft, MIT): construction dates for Change Cases.

GRW detected 86,410 solar farms (polygons) and 375,197 wind turbines (points) worldwide in
quarterly imagery from 2017 Q4 to 2024 Q2, and estimates the quarter each was built. Change
Cases are dated from USGS's install year (`p_year`) first; GRW dates a pair when USGS has no
year, and cross-checks USGS when it has one (caption-plan.md §3).

Two things about GRW's dates matter:

- **2017 Q4 is GRW's first quarter, not a date.** Anything already there when GRW started is
  given 2017 Q4 (147,250 of the turbines), so it means "built by 2017 Q4" and can't bracket a
  Chip Pair. It can still contradict a USGS year of 2019 or later.
- GRW is model-detected, so less exact than USGS in the US; and USGS's year is when a site came
  online, while GRW's quarter is when construction first showed. A gap of up to a year is
  expected; more is flagged for a look by eye, not resolved by picking one.

The two GeoPackages (wind 58 MB, solar 395 MB) download once into the cache, never into git.
They're read with sqlite3 and their R-tree index; geometries are Web Mercator (EPSG:3857).
"""

from __future__ import annotations

import math
import shutil
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from pathlib import Path

from shapely import wkb
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

VERSION = "grw_v1.0_2024q2"
RELEASE = "https://github.com/microsoft/global-renewables-watch/releases/download/v1.0"
FILES = {"solar": "solar_all_2024q2_v1.gpkg", "wind": "wind_all_2024q2_v1.gpkg"}
FIRST = (2017, 4)  # GRW's first quarter: "built by then", not a construction date
R = 6378137.0  # Web Mercator's sphere


@dataclass(frozen=True)
class Feature:
    """One GRW detection, in lon/lat."""

    kind: str  # solar or wind
    fid: int
    year: int
    quarter: int
    geometry: BaseGeometry

    @property
    def censored(self) -> bool:
        """Already there when GRW started: built by 2017 Q4, date unknown."""
        return (self.year, self.quarter) == FIRST

    @property
    def label(self) -> str:
        return f"{'by ' if self.censored else ''}{self.year}Q{self.quarter}"


def quarter_start(year: int, quarter: int) -> date:
    return date(year, 3 * quarter - 2, 1)


def quarter_end(year: int, quarter: int) -> date:
    nxt = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return quarter_start(*nxt) - timedelta(days=1)


def path(kind: str) -> Path:
    """The GeoPackage in the cache, downloaded once (to a .part file, then renamed)."""
    from clayzer.answer_keys import USER_AGENT, _cache_dir

    out = _cache_dir() / "grw" / FILES[kind]
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_suffix(".part")
        req = urllib.request.Request(f"{RELEASE}/{FILES[kind]}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f)
        part.rename(out)
    return out


@cache
def _db(kind: str) -> tuple[sqlite3.Connection, str]:
    con = sqlite3.connect(f"file:{path(kind)}?mode=ro", uri=True, check_same_thread=False)
    (table,) = con.execute(
        "select table_name from gpkg_contents where data_type='features'"
    ).fetchone()
    return con, table


def _to_mercator(lon: float, lat: float) -> tuple[float, float]:
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _to_lonlat(x, y, z=None):
    return (math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))


def _geometry(blob: bytes) -> BaseGeometry:
    """A GeoPackage geometry: a "GP" header (with an envelope whose size the flags give), then
    WKB."""
    flags = blob[3]
    envelope = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 0b111]
    return transform(_to_lonlat, wkb.loads(bytes(blob[8 + envelope :])))


def near(kind: str, bbox, buffer_deg: float = 0.0) -> list[Feature]:
    """GRW detections whose bounding box meets `bbox` (lon/lat, widened by `buffer_deg`)."""
    con, table = _db(kind)
    w, s, e, n = bbox
    x0, y0 = _to_mercator(w - buffer_deg, s - buffer_deg)
    x1, y1 = _to_mercator(e + buffer_deg, n + buffer_deg)
    rows = con.execute(
        f'select t.fid, t.construction_year, t.construction_quarter, t.geom from "{table}" t '
        f'join "rtree_{table}_geom" r on r.id = t.fid '
        "where r.maxx >= ? and r.minx <= ? and r.maxy >= ? and r.miny <= ?",
        (x0, x1, y0, y1),
    ).fetchall()
    return [Feature(kind, fid, int(y), int(q), _geometry(g)) for fid, y, q, g in rows if y and q]


# ── Matching USGS records, and dating a Chip Pair ────────────────────────────────────────

MATCH_M = 50.0  # a GRW turbine this close to a USWTDB one is the same turbine
DISAGREE_YEARS = 1  # USGS's online year and GRW's quarter may differ by this much


def _metres(a: BaseGeometry, b: BaseGeometry) -> float:
    """Distance in metres between two lon/lat shapes, flat-earth (fine at these ranges)."""
    k = 111_320 * math.cos(math.radians(a.centroid.y))
    return a.distance(b) * k


def matches(answer_key: str, rec: dict) -> list[Feature]:
    """GRW's detections of one USGS record: for a turbine, the nearest GRW turbine within
    MATCH_M; for a solar site, every GRW array touching its USPVDB polygon (a site built in
    phases can be several), or within MATCH_M of its point without one."""
    from shapely.geometry import Point

    from clayzer import answer_keys as ak

    point = Point(rec["xlong"], rec["ylat"])
    pad = MATCH_M / 111_320 * 2
    bbox = (point.x, point.y, point.x, point.y)
    if answer_key == "uswtdb":
        near_ = [f for f in near("wind", bbox, pad) if _metres(f.geometry, point) <= MATCH_M]
        return sorted(near_, key=lambda f: f.geometry.distance(point))[:1]
    outline = ak.uspvdb_outlines()[1].get(rec["case_id"])
    if outline is not None:
        return [f for f in near("solar", outline.bounds) if f.geometry.intersects(outline)]
    return [f for f in near("solar", bbox, pad) if _metres(f.geometry, point) <= MATCH_M]


class Flagged(ValueError):
    """USGS and GRW disagree about when a site was built: a person looks first."""


def _window(f_first: Feature, f_last: Feature) -> tuple[str, str]:
    before = quarter_start(f_first.year, f_first.quarter) - timedelta(days=1)
    after = quarter_end(f_last.year, f_last.quarter) + timedelta(days=1)
    return before.isoformat(), after.isoformat()


def dating(answer_key: str, rec: dict, dated_by: str | None = None) -> dict:
    """When a USGS record's site was built, from USGS's year or GRW's quarter, and the window a
    Chip Pair's two NAIP dates must fall either side of (`before`, `after`, inclusive).

    USGS's year comes first; GRW dates the pair only without it, and otherwise cross-checks it.
    When they disagree by more than DISAGREE_YEARS this raises Flagged rather than pick one:
    checked on the dev Cases, each was wrong at times (Pine Tree's panels are in NAIP 2016,
    though GRW says 2018 Q1; Antelope Expansion 1B is bare land in 2020, though USGS says 2016).
    After a look at the site's NAIP images, `dated_by` ("usgs" or "grw") chooses, and the result
    records that a person did. Raises ValueError when neither can date it."""
    year = rec.get("p_year")
    found = matches(answer_key, rec)
    dated = [f for f in found if not f.censored]
    out = {"usgs_year": year, "grw": [f.label for f in found], "grw_fids": [f.fid for f in found],
           "grw_version": VERSION, "flag": None, "chosen_by": None}  # fmt: skip
    if year and dated and (max(f.year for f in dated) < year - DISAGREE_YEARS
                           or min(f.year for f in dated) > year + DISAGREE_YEARS):  # fmt: skip
        out["flag"] = f"USGS says {year}, GRW says {', '.join(f.label for f in dated)}"
    elif year and found and not dated and year > FIRST[0] + DISAGREE_YEARS:
        out["flag"] = f"USGS says {year}, but GRW saw it by {FIRST[0]}Q{FIRST[1]}"
    grw_window = (
        _window(min(dated, key=lambda f: (f.year, f.quarter)),
                max(dated, key=lambda f: (f.year, f.quarter)))
        if dated else None
    )  # fmt: skip
    site = f"{answer_key} {rec['case_id']}"
    if dated_by is None and out["flag"]:
        raise Flagged(f"{site}: {out['flag']}. Look at its NAIP images before and after both "
                      "dates, then rerun with --dated-by usgs or --dated-by grw")  # fmt: skip
    if dated_by not in (None, "usgs", "grw"):
        raise ValueError(f"dated_by must be usgs or grw, not {dated_by!r}")
    use = dated_by or ("usgs" if year else "grw")
    if use == "usgs":
        if not year:
            raise ValueError(f"{site} has no install year (p_year) to date it by")
        out.update(source=answer_key, before=f"{year - 1}-12-31", after=f"{year + 1}-01-01")
    else:
        if grw_window is None:
            why = f"GRW only says built by {FIRST[0]}Q{FIRST[1]}" if found else "GRW has no match"
            raise ValueError(f"{site}: no install year (p_year) to use, and {why}"
                             if not year else f"{site}: {why}, so it can't date the pair")  # fmt: skip
        out.update(source="grw", before=grw_window[0], after=grw_window[1])
    if dated_by:
        out["chosen_by"] = "a person, after a look by eye"
    return out


def built_on(answer_key: str, records: list[dict]) -> dict[str, str]:
    """For USGS records with no year, the last day of the quarter GRW dates them to, by
    case_id; a record GRW can't date (no match, or only "by 2017 Q4") isn't in it."""
    out = {}
    for rec in records:
        if rec.get("p_year"):
            continue
        dated = [f for f in matches(answer_key, rec) if not f.censored]
        if dated:
            last = max(dated, key=lambda f: (f.year, f.quarter))
            out[str(rec["case_id"])] = quarter_end(last.year, last.quarter).isoformat()
    return out
