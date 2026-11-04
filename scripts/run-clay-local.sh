#!/bin/sh
# Local fixtures only. Override model paths or run options with explicit CLI flags.
set -eu
CLAYZER_REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$CLAYZER_REPO/.venv/bin/python" -u "$CLAYZER_REPO/scripts/clay_embed.py" \
  --data-dir "$CLAYZER_REPO/fixtures/caption" \
  --out "$CLAYZER_REPO/data/clay/dev-embeddings.jsonl" "$@"
