"""Fidelity: an image-aware Judge rates the Caption against the Chip (CAP-11).

The Judge sees the image and the Caption, not the Reference Labels: fidelity asks whether the
Caption is an accurate account of the image overall. Opus 5.5 rejects `temperature` and a
forced tool choice, so neither is sent; the prompt asks for the tool instead.
"""

import json
import time

PROMPT = """\
You are judging a caption written for an aerial image (NAIP, 0.6 m per pixel, about 300 m
across, north up). The caption will be used as training text for an Earth observation model.

Caption text:
{text}

Structured claims (positions are cells of a 3x3 grid over the image):
{claims}

Rate how accurately the caption represents the image overall, from 0 to 1:
1.0 accurate and specific; 0.75 accurate with minor errors or omissions; 0.5 partly accurate
or vague; 0.25 mostly inaccurate; 0.0 wrong or unrelated.
List each concrete error or important omission. Submit with the submit_verdict tool.
"""

# A Change Case: the caption describes what changed between two images of one place.
CHANGE_NOTE = """\
There are two images of the same place: the first is the earlier date, the second the later.
The caption describes what changed between them; each structured claim says whether its object
appeared, disappeared, or was unchanged. Judge the account of the change, as well as each image.

"""

VERDICT_TOOL = {
    "toolSpec": {
        "name": "submit_verdict",
        "description": "Submit the fidelity verdict.",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": ["score", "issues"],
                "properties": {
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "issues": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }
}


def fidelity(
    client, model: str, caption: dict, png: bytes, tracer=None, image_key: str | None = None
) -> tuple[dict, dict]:
    """Judge one Caption. With a `tracer`, the call is recorded as a `judge` Step (scoring,
    not Harness activity)."""
    from clayzer.harness import _image_blocks, _image_refs
    from clayzer.trace import image_ref

    claims = json.dumps({"objects": caption["objects"], "relations": caption["relations"]})
    prompt = PROMPT.format(text=caption["text"], claims=claims)
    if isinstance(png, list):  # a Chip Pair
        prompt = CHANGE_NOTE + prompt
    request = {
        "modelId": model,
        "messages": [
            {
                "role": "user",
                "content": [*_image_blocks(png), {"text": prompt}],
            }
        ],
        "toolConfig": {"tools": [VERDICT_TOOL]},
        "inferenceConfig": {"maxTokens": 1000},
    }
    started = time.monotonic()
    if tracer is None:
        resp = client.converse(**request)
    else:
        recorded = {
            "prompt": prompt,
            "image": _image_refs(png, image_key, "chip")
            if isinstance(png, list)
            else image_ref(image_key or "chip", png),
            "tools": ["submit_verdict"],
            "max_tokens": 1000,
        }
        resp = tracer.converse(
            client, "judge", "fidelity", request, recorded, {"expects_tool": "submit_verdict"}
        )
    blocks = resp["output"]["message"]["content"]
    verdict = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    step = {
        "step": "judge",
        "model": model,
        "seconds": round(time.monotonic() - started, 2),
        "usage": resp.get("usage", {}),
        "ok": verdict is not None,
    }
    if verdict is None:
        raise RuntimeError(f"{model} returned no submit_verdict call")
    return {"score": float(verdict["score"]), "issues": verdict.get("issues", [])}, step
