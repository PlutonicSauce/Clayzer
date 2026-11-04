#!/usr/bin/env python3
"""Embed RGB NAIP chips with the local Clay v1.5 encoder, without training services.

See scripts/CLAY_LOCAL.md for setup and commands. The model source and checkpoint
remain outside this repository. No weights are downloaded by this script.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from clayzer.cases import cases_key, load_cases
from clayzer.config import Settings, load_env

NAIP_GSD_M = 0.6
NAIP_WAVES = [0.65, 0.56, 0.48]


def _chip_meta(case: dict, chip: dict) -> dict:
    bbox = chip.get("bbox")
    if not bbox or len(bbox) != 4:
        raise ValueError(f"Chip {chip['id']} needs a WGS84 bbox")
    lat, lon = (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Chip {chip['id']} has invalid coordinates")
    _norm_date(chip.get("date"))  # Fail on missing/invalid metadata before model loading.
    return {"id": chip["id"], "uri": chip["uri"], "date": chip["date"], "lat": lat, "lon": lon}


def _norm_date(value: str | None) -> list[float]:
    if not value:
        raise ValueError("Clay requires the chip acquisition date")
    timestamp = dt.datetime.fromisoformat(value)
    week = timestamp.isocalendar().week * 2 * math.pi / 52
    hour = timestamp.hour * 2 * math.pi / 24
    return [math.sin(week), math.cos(week), math.sin(hour), math.cos(hour)]


def _load_pixels(png: bytes, mean, std, image_size: int | None = None):
    """Normalize raw RGB DN values with Clay's NAIP metadata; retain full footprint."""
    import numpy as np
    import torch
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        if img.mode != "RGB" or img.width != img.height:
            raise ValueError(
                "Expected square RGB NAIP chips; other sensors need their own metadata"
            )
        original_size = img.width
        size = image_size or original_size
        if size % 8:
            raise ValueError("Chip size must be a multiple of Clay's 8-pixel patch size")
        if size != original_size:
            img = img.resize((size, size), Image.Resampling.BILINEAR)
        arr = np.array(img, dtype="float32", copy=True)
    pixels = torch.from_numpy(arr).permute(2, 0, 1)
    mean = torch.tensor(mean, dtype=torch.float32)[:, None, None]
    std = torch.tensor(std, dtype=torch.float32)[:, None, None]
    return (pixels - mean) / std, NAIP_GSD_M * original_size / size


def _pick_device(requested: str) -> str:
    import torch

    available = {
        "cuda": torch.cuda.is_available(),
        "mps": torch.backends.mps.is_available(),
        "cpu": True,
    }
    if requested != "auto":
        if not available[requested]:
            raise ValueError(f"Requested device {requested!r} is unavailable")
        return requested
    return next(device for device, ok in available.items() if ok)


def _load_encoder(checkpoint: Path, model_dir: Path, device: str = "auto"):
    """Strict encoder-only loading; mmap avoids reading 5 GB of training state into RAM."""
    import torch
    import yaml

    checkpoint, model_dir = checkpoint.expanduser().resolve(), model_dir.expanduser().resolve()
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    if not (model_dir / "claymodel/model.py").is_file():
        raise FileNotFoundError(f"No claymodel/model.py in {model_dir}")
    sys.path.insert(0, str(model_dir))
    from claymodel.model import Encoder

    device = _pick_device(device)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True, mmap=True)
    hp = saved.get("hyper_parameters", {})
    if hp.get("model_size") != "large" or hp.get("patch_size") != 8:
        raise ValueError("Expected a Clay v1.5 large checkpoint with patch_size=8")
    prefix = "model.encoder."
    weights = {
        k.removeprefix(prefix): v for k, v in saved["state_dict"].items() if k.startswith(prefix)
    }
    # Allocate no random 300M-parameter copy. Strict loading rejects absent/extra/wrong weights.
    with torch.device("meta"):
        model = Encoder(
            mask_ratio=0.0,
            patch_size=8,
            shuffle=False,
            dim=1024,
            depth=24,
            heads=16,
            dim_head=64,
            mlp_ratio=4,
        )
    model.load_state_dict(weights, strict=True, assign=True)
    del saved
    model.requires_grad_(False).eval().to(device)
    metadata = yaml.safe_load((model_dir / "configs/metadata.yaml").read_text())["naip"]
    bands = metadata["bands"]
    names = ["red", "green", "blue"]
    mean, std = ([bands[k][name] for name in names] for k in ("mean", "std"))
    waves = [bands["wavelength"][name] for name in names]
    if waves != NAIP_WAVES or any(s <= 0 for s in std):
        raise ValueError("Unexpected NAIP normalization/wavelength metadata")
    print(f"  loaded all {len(weights)} encoder tensors; device: {device}", flush=True)
    return model, device, mean, std


def _embed_batch(model, device, pixels_list, metas, gsd=NAIP_GSD_M) -> list[list[float]]:
    import torch

    latlon = [
        [
            math.sin(math.radians(m["lat"])),
            math.cos(math.radians(m["lat"])),
            math.sin(math.radians(m["lon"])),
            math.cos(math.radians(m["lon"])),
        ]
        for m in metas
    ]
    datacube = {
        "pixels": torch.stack(pixels_list).to(device),
        "time": torch.tensor(
            [_norm_date(m["date"]) for m in metas], dtype=torch.float32, device=device
        ),
        "latlon": torch.tensor(latlon, dtype=torch.float32, device=device),
        "waves": torch.tensor(NAIP_WAVES, dtype=torch.float32, device=device),
        "gsd": torch.tensor(gsd, dtype=torch.float32, device=device),
    }
    with torch.inference_mode():
        encoded, *_ = model(datacube)
        vectors = encoded[:, 0, :].cpu()
    if (
        vectors.shape != (len(metas), 1024)
        or not vectors.is_floating_point()
        or not torch.isfinite(vectors).all()
    ):
        raise ValueError("Clay returned invalid embedding dimensions or non-finite values")
    if (torch.linalg.vector_norm(vectors, dim=1) == 0).any():
        raise ValueError("Clay returned a zero embedding")
    return vectors.tolist()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="dev")
    ap.add_argument("--out", type=Path, required=True)
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--data-dir", type=Path, help="local store; bypass .env and cloud settings")
    source.add_argument("--store", help="explicit store URL, e.g. s3://bucket/prefix")
    ap.add_argument("--model-dir", type=Path, default=Path.home() / "Downloads/model-main")
    ap.add_argument("--checkpoint", type=Path, default=Path.home() / "Downloads/clay-v1.5.ckpt")
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--limit", type=int, help="embed only the first N unique chips for a smoke run")
    ap.add_argument(
        "--image-size", type=int, help="optional square resize; adjusts GSD accordingly"
    )
    ap.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output")
    a = ap.parse_args(argv)
    if a.batch_size < 1 or (a.limit is not None and a.limit < 1):
        ap.error("--batch-size and --limit must be positive")
    if a.image_size is not None and (a.image_size < 8 or a.image_size % 8):
        ap.error("--image-size must be a positive multiple of 8")
    a.out = a.out.expanduser().resolve()
    if a.out.exists() and not a.overwrite:
        ap.error(f"output exists: {a.out}; choose another path or pass --overwrite")
    if a.data_dir:
        from clayzer.store import open_store

        store = open_store(None, a.data_dir.resolve(), REPO / "batches")
    else:
        from dataclasses import replace

        load_env()
        settings = Settings.from_env()
        store = replace(settings, store_url=a.store or settings.store_url).store()
    cases = load_cases(store, cases_key(a.region))
    if not cases:
        ap.error(f"no Cases for region {a.region!r}; use --data-dir fixtures/caption")
    unique = {}
    for case in cases:
        for chip in case["chips"]:
            meta = _chip_meta(case, chip)
            if meta["id"] in unique and unique[meta["id"]] != meta:
                raise ValueError(f"Conflicting metadata for chip {meta['id']}")
            unique[meta["id"]] = meta
    chips = list(unique.values())[: a.limit]
    if not chips:
        ap.error("no Chips in selected Cases")
    print(f"embedding {len(chips)} unique Chips from region {a.region!r}...", flush=True)
    start = time.monotonic()
    model, device, mean, std = _load_encoder(a.checkpoint, a.model_dir, a.device)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    # A failed run never leaves a plausible-looking final JSONL.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=a.out.parent, suffix=".partial", delete=False
    ) as f:
        partial = Path(f.name)
        try:
            for i in range(0, len(chips), a.batch_size):
                metas = chips[i : i + a.batch_size]
                loaded = [_load_pixels(store.get(m["uri"]), mean, std, a.image_size) for m in metas]
                if len({gsd for _, gsd in loaded}) != 1:
                    raise ValueError("A batch must have matching chip dimensions/GSD")
                vectors = _embed_batch(model, device, [p for p, _ in loaded], metas, loaded[0][1])
                for meta, vec in zip(metas, vectors, strict=True):
                    f.write(json.dumps({"chip_id": meta["id"], "embedding": vec}) + "\n")
                print(
                    f"  {i + len(metas)}/{len(chips)} ({time.monotonic() - start:.1f}s)", flush=True
                )
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    partial.replace(a.out)
    provenance = {
        "model": "clay-v1.5",
        "checkpoint": str(a.checkpoint.expanduser().resolve()),
        "checkpoint_bytes": a.checkpoint.expanduser().stat().st_size,
        "model_dir": str(a.model_dir.expanduser().resolve()),
        "device": device,
        "region": a.region,
        "chips": len(chips),
        "dimension": 1024,
        "image_size": a.image_size or "native",
        "mean": mean,
        "std": std,
        "waves": NAIP_WAVES,
        "native_gsd_m": NAIP_GSD_M,
        "time_encoding": "iso-week/52,hour/24",
        "pooling": "cls",
        "seconds": round(time.monotonic() - start, 2),
    }
    a.out.with_suffix(a.out.suffix + ".meta.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(f"wrote {len(chips)} embeddings (dim 1024) → {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
