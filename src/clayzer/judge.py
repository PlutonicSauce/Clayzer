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


def fidelity(client, model: str, caption: dict, png: bytes) -> tuple[dict, dict]:
    claims = json.dumps({"objects": caption["objects"], "relations": caption["relations"]})
    started = time.monotonic()
    resp = client.converse(
        modelId=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": png}}},
                    {"text": PROMPT.format(text=caption["text"], claims=claims)},
                ],
            }
        ],
        toolConfig={"tools": [VERDICT_TOOL]},
        inferenceConfig={"maxTokens": 1000},
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
