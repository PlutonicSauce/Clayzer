"""Standalone inference checks; requires requirements-clay.txt, no checkpoint or network."""

import importlib.util
import io
import math
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

spec = importlib.util.spec_from_file_location(
    "clay_embed", Path(__file__).with_name("clay_embed.py")
)
embed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(embed)


def png(size=16, mode="RGB"):
    output = io.BytesIO()
    color = (110, 115, 98) if mode == "RGB" else 110
    Image.new(mode, (size, size), color=color).save(output, format="PNG")
    return output.getvalue()


def test_raw_dn_normalization_and_resize_gsd():
    pixels, gsd = embed._load_pixels(png(), [110.16, 115.41, 98.15], [47.23, 39.82, 35.43], 8)
    assert pixels.shape == (3, 8, 8)
    np.testing.assert_allclose(
        pixels[:, 0, 0],
        (np.array([110, 115, 98]) - [110.16, 115.41, 98.15]) / [47.23, 39.82, 35.43],
        atol=1e-6,
    )
    assert gsd == 1.2


@pytest.mark.parametrize("body", [png(mode="L"), png(size=15)])
def test_incompatible_pixels_rejected(body):
    with pytest.raises(ValueError):
        embed._load_pixels(body, [1, 1, 1], [1, 1, 1])


def test_time_matches_clay_iso_week_and_hour():
    # January 1 belongs to ISO week 53 in 2021; day-of-year encoding is incorrect.
    expected = [math.sin(53 * 2 * math.pi / 52), math.cos(53 * 2 * math.pi / 52), 1, 0]
    np.testing.assert_allclose(embed._norm_date("2021-01-01T06:00:00Z"), expected, atol=1e-6)
    with pytest.raises(ValueError):
        embed._norm_date(None)


def test_bbox_center_and_missing_bbox():
    chip = {"id": "a", "uri": "chips/a.png", "date": "2022-01-01", "bbox": [-120, 30, -118, 32]}
    meta = embed._chip_meta({}, chip)
    assert (meta["lon"], meta["lat"]) == (-119, 31)
    with pytest.raises(ValueError):
        embed._chip_meta({}, {**chip, "bbox": None})


@pytest.mark.parametrize("invalid", ["nan", "zero", "shape"])
def test_invalid_model_outputs_rejected(invalid):
    def model(cube):
        assert cube["time"].shape == (1, 4)
        assert cube["latlon"].shape == (1, 4)
        size = 768 if invalid == "shape" else 1024
        value = float("nan") if invalid == "nan" else 0
        return (torch.full((1, 2, size), value, dtype=torch.float32),)

    with pytest.raises(ValueError):
        embed._embed_batch(
            model, "cpu", [torch.zeros(3, 8, 8)], [{"lat": 35, "lon": -119, "date": "2022-01-01"}]
        )


def test_encoder_checkpoint_must_exist(tmp_path):
    with pytest.raises(FileNotFoundError):
        embed._load_encoder(tmp_path / "absent.ckpt", tmp_path)


def test_cli_rejects_invalid_batch_size(tmp_path):
    with pytest.raises(SystemExit) as exc:
        embed.main(["--out", str(tmp_path / "out.jsonl"), "--batch-size", "0"])
    assert exc.value.code == 2
