"""Chips come from one NAIP tile that covers them whole, never partly blank."""

from datetime import datetime
from types import SimpleNamespace

import numpy as np
from shapely.geometry import box

from clayzer.chips import RES, SIZE, blank_share, chip_footprint, covering_item


def item(name, year, bounds):
    return SimpleNamespace(
        id=name, datetime=datetime(year, 6, 1), geometry=box(*bounds).__geo_interface__
    )


def test_the_footprint_is_a_chip_wide_and_moves_with_the_offset():
    f = chip_footprint(-118.0, 35.0)
    w, s, _, n = f.bounds
    assert (n - s) * 111_320 > SIZE * RES  # a Chip's height plus the margin
    moved = chip_footprint(-118.0, 35.0, offset_m=(100.0, 0.0))
    assert moved.bounds[0] > w and moved.bounds[1] == s


def test_the_newest_tile_that_covers_the_whole_chip_wins():
    footprint = chip_footprint(-118.0, 35.0)
    edge = item("newest, but the Chip crosses its edge", 2022, (-118.0, 34.9, -117.9, 35.1))
    whole = item("older, covers it", 2020, (-118.1, 34.9, -117.9, 35.1))
    newer_whole = item("newer, covers it", 2022, (-118.05, 34.95, -117.95, 35.05))
    assert covering_item([edge, whole], footprint) is whole
    assert covering_item([edge, whole, newer_whole], footprint) is newer_whole
    assert covering_item([edge], footprint) is None


def test_blank_pixels_are_measured():
    rgb = np.full((3, 10, 10), 120, dtype=np.uint8)
    assert blank_share(rgb) == 0.0
    rgb[:, :5, :] = 0
    assert blank_share(rgb) == 0.5
    rgb[0, 0, 0] = 9  # one band non-zero: not blank
    assert blank_share(rgb) == 0.49
