"""RSICD's human captions as a Caption Set (caption-design.md §3.6), to test the importer on
captions we didn't write.

RSICD (Lu et al. 2017) has 10,921 aerial images, five human captions each, split 8,734 / 1,094 /
1,093. Its images come from commercial map services with no location, date, or published ground
sample distance, so every row is unlocated (`geometry`, `datetime`, and `gsd_m` null): the
Cases can be judged for fidelity and retrieval but not grounded, and too-small Claims can't be
checked. The captions file is downloaded at run time into the cache and never committed (no
license is stated; cite Lu et al. 2017).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/201528014227051/RSICD_optimal/master/dataset_rsicd.json"
SPLITS = ("train", "val", "test")
GENERATOR = "human (RSICD, Lu et al. 2017)"


def captions_file() -> Path:
    """dataset_rsicd.json in the cache, downloaded once (12 MB)."""
    from clayzer.answer_keys import _cache_dir

    path = _cache_dir() / "rsicd" / "dataset_rsicd.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL, headers={"User-Agent": "clayzer"})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
        json.loads(body)  # a truncated download fails here, not in the cache
        path.write_bytes(body)
    return path


def scene(filename: str) -> str | None:
    """The scene class in an image's filename (`airport_348.jpg` is `airport`); some test images
    are only numbered (`00623.jpg`) and have none."""
    stem = filename.rsplit(".", 1)[0]
    return stem.rsplit("_", 1)[0] if "_" in stem else None


def rows(dataset: dict, split: str = "test", limit: int | None = None) -> list[dict]:
    """One Caption Set row per human caption of the split's images (the first `limit` images).
    Repeated captions are kept: duplication is something the dataset card measures."""
    images = [im for im in dataset["images"] if im["split"] == split][:limit]
    out = []
    for im in images:
        for s in im["sentences"]:
            out.append({
                "caption_id": f"rsicd-{im['imgid']}-{s['sentid']}",
                "chip_id": f"rsicd-{im['filename'].rsplit('.', 1)[0]}",
                "caption": s["raw"].strip(),
                "kind": "fixed",
                "geometry": None,
                "datetime": None,
                "sensor": "rsicd",
                "gsd_m": None,
                "generator": GENERATOR,
                "scene": scene(im["filename"]),
            })  # fmt: skip
    return out
