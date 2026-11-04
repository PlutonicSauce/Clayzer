#!/usr/bin/env python3
"""Embed Clayzer Chips with the Clay foundation model, for Layer B of the ontology (ADR-0010).

This is a STANDALONE script, not part of the `clayzer` package: it pulls in torch and the Clay
model, which are heavy and want a GPU, so they stay out of the tested package and its lockfile.
Run it once, offline, on a machine where Clay is installed; it writes a `{chip_id, embedding}`
JSONL that feeds the normal reuse path:

    # on a Clay-capable box (a CPU instance is fine for a few dozen Chips; GPU only helps at scale):
    pip install git+https://github.com/Clay-foundation/model.git   # https://clay-foundation.github.io/model/getting-started/installation.html

    # read the committed fixtures directly — no store setup needed:
    CLAYZER_DATA_DIR=$PWD/fixtures/caption \
        python scripts/clay_embed.py --region dev --out dev-embeddings.jsonl --device cpu \
        [--checkpoint path/to/clay.ckpt]
    # (or point at an S3 store with --store s3://your-bucket/prefix instead of CLAYZER_DATA_DIR)

    # then, back with the clayzer package:
    clayzer ontology embed-cases --region dev --source file --from dev-embeddings.jsonl
    clayzer ontology build-prototypes --region dev --build-region dev \
        --source clay --embedding-model clay-v1.5
    # score a DIFFERENT region with `clayzer batch --region held-out --ontology-context`

Keeping Clay inference here (one vector per Chip, computed once) preserves the cost guard: a
caption never calls a model for its embedding — it reads the stored vector and does a dot product.

NOTE ON THE CLAY API. The datacube fields and encoder call below follow Clay's documented
inference shape, but Clay's API moves between versions. The one place that is version-specific is
`_load_encoder` / `_embed_batch`; verify those two against your installed Clay before trusting the
output (the script prints the embedding dimension it got, as a sanity check). Everything else —
reading Cases, loading Chip pixels, batching, writing JSONL — is plain and stable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The clayzer package is only used for its store/Case helpers, which are light.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from clayzer.cases import cases_key, load_cases  # noqa: E402
from clayzer.config import Settings, load_env  # noqa: E402

# NAIP defaults (the imagery Clayzer cuts Chips from). Override with flags if your Chips differ.
NAIP_GSD_M = 0.6
NAIP_WAVES = [0.65, 0.56, 0.48]  # red, green, blue centre wavelengths (µm); add NIR 0.84 if 4-band


def _chip_meta(case: dict, chip: dict) -> dict:
    bbox = chip.get("bbox")
    lat = (bbox[1] + bbox[3]) / 2 if bbox else 0.0
    lon = (bbox[0] + bbox[2]) / 2 if bbox else 0.0
    return {"id": chip["id"], "uri": chip["uri"], "date": chip.get("date"), "lat": lat, "lon": lon}


def _load_pixels(png: bytes):
    """Chip PNG -> a (C, H, W) float tensor, C in the order of NAIP_WAVES."""
    import io

    import numpy as np
    import torch
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    arr = np.asarray(img, dtype="float32") / 255.0  # (H, W, 3)
    return torch.from_numpy(arr).permute(2, 0, 1)  # (3, H, W)


def _pick_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_encoder(checkpoint: str | None, device: str = "auto"):
    """Load the Clay encoder. VERSION-SPECIFIC — confirm against your installed Clay."""
    try:
        import torch  # noqa: F401
        from claymodel.module import ClayMAEModule  # Clay v1.x packaging
    except ImportError:
        raise SystemExit(
            "Clay isn't installed. See "
            "https://clay-foundation.github.io/model/getting-started/installation.html\n"
            "  pip install git+https://github.com/Clay-foundation/model.git"
        )
    import torch  # noqa: F811

    device = _pick_device(device)
    if checkpoint:
        model = ClayMAEModule.load_from_checkpoint(checkpoint, map_location=device)
    else:
        model = ClayMAEModule()  # uses Clay's default/pretrained weights if the package bundles them
    model.eval().to(device)
    return model, device


def _embed_batch(model, device, pixels_list, metas) -> list[list[float]]:
    """Run the Clay encoder on a batch of Chips and return one vector each. VERSION-SPECIFIC."""
    import datetime as dt

    import torch

    def norm_date(d: str | None):
        if not d:
            return [0.0, 0.0, 0.0, 0.0]
        t = dt.date.fromisoformat(d[:10])
        import math

        week, hour = (t.timetuple().tm_yday / 365.0) * 2 * math.pi, 0.0
        return [math.sin(week), math.cos(week), math.sin(hour), math.cos(hour)]

    pixels = torch.stack(pixels_list).to(device)
    latlon, time = [], []
    for m in metas:
        import math

        latlon.append([math.sin(math.radians(m["lat"])), math.cos(math.radians(m["lat"])),
                       math.sin(math.radians(m["lon"])), math.cos(math.radians(m["lon"]))])  # fmt: skip
        time.append(norm_date(m["date"]))
    datacube = {
        "pixels": pixels,
        "time": torch.tensor(time, dtype=torch.float32, device=device),
        "latlon": torch.tensor(latlon, dtype=torch.float32, device=device),
        "waves": torch.tensor(NAIP_WAVES, dtype=torch.float32, device=device),
        "gsd": torch.tensor(NAIP_GSD_M, dtype=torch.float32, device=device),
    }
    with torch.no_grad():
        encoded, *_ = model.model.encoder(datacube)  # (B, 1 + num_patches, dim)
    # The class token (index 0) is the standard per-Chip embedding.
    return encoded[:, 0, :].cpu().tolist()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Embed a region's Chips with the Clay model.")
    ap.add_argument("--region", default="dev")
    ap.add_argument("--out", type=Path, required=True, help="output JSONL of {chip_id, embedding}")
    ap.add_argument("--store", help="CLAYZER_STORE url (default: local data/ folder)")
    ap.add_argument("--checkpoint", help="a Clay checkpoint; omit to use the package default")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto",
                    help="force a device; CPU is fine for a few dozen Chips")  # fmt: skip
    a = ap.parse_args(argv)

    load_env()
    settings = Settings.from_env()
    if a.store:
        import os

        os.environ["CLAYZER_STORE"] = a.store
        settings = Settings.from_env()
    store = settings.store()

    cases = load_cases(store, cases_key(a.region))
    if not cases:
        print(f"no Cases for region {a.region!r}", file=sys.stderr)
        return 1
    chips = [(_chip_meta(c, ch), ch["uri"]) for c in cases for ch in c["chips"]]
    print(f"embedding {len(chips)} Chips from region {a.region!r} with Clay...")

    model, device = _load_encoder(a.checkpoint, a.device)
    print(f"  device: {device}")
    written, dim = 0, None
    with a.out.open("w") as f:
        for i in range(0, len(chips), a.batch_size):
            batch = chips[i : i + a.batch_size]
            metas = [m for m, _ in batch]
            pixels = [_load_pixels(store.get(uri)) for _, uri in batch]
            vectors = _embed_batch(model, device, pixels, metas)
            for meta, vec in zip(metas, vectors):
                dim = dim or len(vec)
                f.write(json.dumps({"chip_id": meta["id"], "embedding": vec}) + "\n")
                written += 1
            print(f"  {written}/{len(chips)}")
    print(f"wrote {written} embeddings (dim {dim}) → {a.out}")
    print("next: clayzer ontology embed-cases --region "
          f"{a.region} --source file --from {a.out}")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
