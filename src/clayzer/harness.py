"""The caption Harness: one Chip in, one Caption out (caption-plan.md §1.3, §5.2).

It sees only the Chip's id and image, never the Case or its Reference Labels (ADR-0006).
Walking-skeleton version: a single VLM call with structured output. Verify-then-write and the
caption MCP server come next.
"""

import time

from clayzer.grid import GRID, RELATIONS

OBJECTS = (
    "solar_array", "wind_turbine", "road", "railroad", "building", "water", "field",
    "parking_lot", "greenhouse", "vegetation", "bare_ground",
)  # fmt: skip

PROMPT = """\
This is an aerial image (NAIP, 0.6 m per pixel, about 300 m across, north is up).
Write a caption for it as training text for an Earth observation model, then submit it with
the submit_caption tool.

- text: 1 to 3 sentences describing what is on the ground, where, how many, and how things
  sit relative to each other. Plain and specific; no speculation.
- objects: every object type you assert, with a count and a position. Position is one cell
  of a 3x3 grid over the image: {grid}. Use the cell holding most of the object.
  Allowed object types: {objects}.
  Attributes, only where visible: solar_array size (small, medium, large);
  road surface (paved, unpaved).
- relations: how objects sit relative to each other, from: {relations}.
- uncertain: anything you think may be there but would not assert.
"""

CAPTION_TOOL = {
    "toolSpec": {
        "name": "submit_caption",
        "description": "Submit the caption for the image.",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": ["text", "objects", "relations", "uncertain"],
                "properties": {
                    "text": {"type": "string"},
                    "objects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "object", "count", "position"],
                            "properties": {
                                "id": {"type": "string", "description": "o1, o2, ..."},
                                "object": {"type": "string", "enum": list(OBJECTS)},
                                "count": {"type": "integer", "minimum": 1},
                                "position": {"type": "string", "enum": list(GRID)},
                                "attributes": {
                                    "type": "object",
                                    "properties": {
                                        "size": {"enum": ["small", "medium", "large"]},
                                        "surface": {"enum": ["paved", "unpaved"]},
                                    },
                                },
                            },
                        },
                    },
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["subject", "relation", "object"],
                            "properties": {
                                "subject": {"type": "string"},
                                "relation": {"type": "string", "enum": list(RELATIONS)},
                                "object": {"type": "string"},
                            },
                        },
                    },
                    "uncertain": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }
}


class HarnessFault(Exception):
    """The Harness produced no usable Caption: the system under test's fault, scored as 0."""

    def __init__(self, message: str, step: dict):
        super().__init__(message)
        self.step = step


def caption(
    client, model: str, chip_id: str, png: bytes, prompt_template: str = PROMPT
) -> tuple[dict, dict]:
    """Caption one Chip. Returns the Caption (minus `case_id`) and a Trace Step.

    `prompt_template` may use {grid}, {objects}, and {relations}.
    """
    prompt = prompt_template.format(
        grid=", ".join(GRID), objects=", ".join(OBJECTS), relations=", ".join(RELATIONS)
    )
    started = time.monotonic()
    resp = client.converse(
        modelId=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": png}}},
                    {"text": prompt},
                ],
            }
        ],
        toolConfig={"tools": [CAPTION_TOOL], "toolChoice": {"tool": {"name": "submit_caption"}}},
        inferenceConfig={"maxTokens": 1500},
    )
    seconds = round(time.monotonic() - started, 2)
    blocks = resp["output"]["message"]["content"]
    submitted = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    step = {
        "step": "caption",
        "chip_id": chip_id,
        "model": model,
        "seconds": seconds,
        "usage": resp.get("usage", {}),
        "stop_reason": resp.get("stopReason"),
        "ok": submitted is not None,
    }
    if submitted is None:
        raise HarnessFault(f"{model} returned no submit_caption call for {chip_id}", step)
    return _clean(submitted), step


def _clean(c: dict) -> dict:
    """Keep only well-formed Claims; drop relations to unknown object ids."""
    objects = [
        o for o in c.get("objects", [])
        if o.get("object") in OBJECTS and o.get("position") in GRID and isinstance(o.get("count"), int)
    ]  # fmt: skip
    ids = {o["id"] for o in objects}
    relations = [
        r for r in c.get("relations", [])
        if r.get("relation") in RELATIONS and r.get("subject") in ids and r.get("object") in ids
    ]  # fmt: skip
    return {
        "text": c.get("text", ""),
        "objects": objects,
        "relations": relations,
        "uncertain": c.get("uncertain", []),
    }
