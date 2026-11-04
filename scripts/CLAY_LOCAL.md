# Local Clay v1.5 embeddings

Standalone inference setup for `feat/ontology-data-driven`, prepared from
`1397c39`. Create an isolated `.venv` using the setup command below before running.

The launcher uses **local committed dev fixtures**, not `.env` or an AWS store.
It reads these existing files without modifying them:

- `~/Downloads/model-main/claymodel/model.py`
- `~/Downloads/model-main/configs/metadata.yaml`
- `~/Downloads/clay-v1.5.ckpt`

From this checkout, run all dev chips:

```sh
./scripts/run-clay-local.sh
```

Output: `data/clay/dev-embeddings.jsonl`, plus `.meta.json` recording preprocessing,
model path, device and elapsed time. Existing outputs require `--overwrite`.
No checkpoints or embeddings are committed. No model download or cloud inference
is performed. The script does not upload the checkpoint.

Small native-resolution check:

```sh
./scripts/run-clay-local.sh --limit 1 --device cpu --out data/clay/my-smoke.jsonl
```

The checked-in chips are 512×512 RGB at 0.6 m/pixel. Defaults retain native
resolution and use batches of one. `--device auto` prefers CUDA, then Apple MPS,
then CPU; force `--device cpu` if GPU execution is unavailable.
`--image-size 256` is an optional speed/memory tradeoff: it resamples the entire
chip and adjusts GSD to 1.2 m/pixel. Resizing changes the resulting embeddings;
use the same preprocessing for prototypes and query chips.

Override paths with `--model-dir /path/to/model-main --checkpoint /path/to/clay-v1.5.ckpt`.
To use different local Cases, pass `--data-dir /path/to/store --region REGION`.

The loader reads only encoder weights from the checkpoint using restricted
`weights_only=True`, memory mapping and strict key/shape validation. It does not
instantiate the Lightning training module or teacher model. RGB bands use the
NAIP raw-DN means/stds and wavelengths from local Clay metadata. Time uses Clay's
ISO-week and hour encoding. Output is the official embedder's class token,
1,024 finite nonzero values per unique chip. Conflicting duplicate IDs fail.
Final JSONL appears only after the full selected run succeeds.

A real native-resolution CPU run with the downloaded checkpoint completed all
63 dev fixture chips in 391.38 seconds including model loading. Every chip had a
finite, nonzero 1,024-dimensional vector, with no missing or duplicate IDs.
The standalone, ontology and embedding tests also passed (45 tests). This verifies
execution and output structure; it does not establish downstream retrieval quality.

To recreate this environment with uv and Python 3.12:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . 'rasterio==1.4.3' -r scripts/requirements-clay.txt
```

The rasterio pin uses a prebuilt macOS wheel. Heavy inference dependencies remain
separate from the Clayzer package. For the standalone script checks, install
`pytest` and run `.venv/bin/python -m pytest scripts/test_clay_embed.py -q`.

After a **complete** run, import vectors into a writable local data store using
Clayzer's `ontology embed-cases --source file --from ...` command. The embedding
run itself does not change Cases or build prototypes. Do not import the one-chip
smoke file as a complete region.
