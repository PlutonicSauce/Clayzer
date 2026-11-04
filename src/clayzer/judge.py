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


def recorded_verdict(steps) -> dict | None:
    """The fidelity verdict a Run's Trace recorded, or None if it recorded none.

    Replay reads this instead of asking the Judge again (REQ-09): the Judge Step keeps the
    model's full response, so the verdict can be recovered from the Trace alone.
    """
    for step in reversed(steps):
        if step.kind != "judge" or step.name != "fidelity" or step.error:
            continue
        for block in (step.output or {}).get("content", []):
            call = block.get("toolUse") or {}
            verdict = call.get("input") or {}
            if call.get("name") == "submit_verdict" and "score" in verdict:
                return {"score": float(verdict["score"]), "issues": verdict.get("issues", [])}
    return None


def fidelity(
    client, model: str, caption: dict, png: bytes, tracer=None, image_key: str | None = None
) -> tuple[dict, dict]:
    """Judge one Caption. With a `tracer`, the call is recorded as a `judge` Step (scoring,
    not Harness activity)."""
    from clayzer.trace import image_ref

    claims = json.dumps({"objects": caption["objects"], "relations": caption["relations"]})
    prompt = PROMPT.format(text=caption["text"], claims=claims)
    request = {
        "modelId": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": png}}},
                    {"text": prompt},
                ],
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
            "image": image_ref(image_key or "chip", png),
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
