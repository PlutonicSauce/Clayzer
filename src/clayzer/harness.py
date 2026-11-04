"""The caption Harness: one Chip in, one Caption out (caption-plan.md §1.3, §5.2).

It sees only the Chip's id and image, never the Case or its Reference Labels (ADR-0006).

Without tools it's a single VLM call with structured output. With a Toolbox of MCP servers
(tools.py) it's a plain tool-use loop (ADR-0002): a model turn, its tool calls, their results,
repeat, until the model calls `submit_caption` or the turn budget runs out. Every model turn is
an `llm` Step and every tool call a `tool` Step in the Run's Trace (REQ-01).

With verification (verify.py), the drafted Claims are then checked against LGND Geo's imagery,
unconfirmed ones move to `uncertain`, and if any moved, a text-only call rewrites the prose from
the Claims that are left: verify, then write.
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

TOOLS_NOTE = """
You also have geospatial data tools (catalogs and open-data registries). You may call them to
look things up before you write, for example to check what imagery or data covers this place.
They don't show you this image, so describe only what the image itself shows. Call
submit_caption exactly once, when you're done.
"""

MAX_TURNS = 8  # model turns per Caption in the tool-use loop
MAX_TOOL_TEXT = 20_000  # characters of one tool result the model sees; the Trace keeps it all

REWRITE_PROMPT = """\
Below is a draft caption of an aerial image (NAIP, 0.6 m per pixel, about 300 m across, north
up), and the Claims that survived a check against imagery. Some drafted Claims weren't
confirmed and are gone. Rewrite the caption text so it states only the confirmed Claims: their
objects, counts, positions, and relations. Don't mention anything that isn't in them. 1 to 3
plain sentences. Submit it with the submit_caption tool, listing the confirmed Claims as they
are.

Draft text: {text}

Confirmed Claims: {claims}
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
    client,
    model: str,
    chip_id: str,
    png: bytes,
    prompt_template: str = PROMPT,
    tracer=None,
    image_key: str | None = None,
    toolbox=None,
    max_turns: int = MAX_TURNS,
    verifier=None,
    footprint: dict | None = None,
    ontology_context: str | None = None,
) -> tuple[dict, dict]:
    """Caption one Chip, and with a `verifier` (a Toolbox with LGND Geo) and the Chip's
    `footprint`, verify its Claims and rewrite it from the confirmed ones (verify.py).

    `ontology_context` is class-level guidance from the Object Ontology (look-alikes, minimum
    sizes, caption exemplars, and an embedding-nearest-class hint): general knowledge, never the
    Case's Answer Key, so ADR-0006 still holds. See ontology.py and prototypes.py (ADR-0010).

    The rest is `_draft`'s: see there."""
    cap, step = _draft(client, model, chip_id, png, prompt_template, tracer, image_key,
                       toolbox, max_turns, ontology_context)  # fmt: skip
    if verifier is None or footprint is None:
        return cap, step
    from clayzer.verify import verify

    cap, report = verify(cap, footprint, verifier, tracer)
    step["verification"] = {k: v for k, v in report.items() if k != "checks"}
    if tracer is not None:
        tracer.run.metadata["verification"] = report
    if report["moved"]:
        cap["text"] = _rewrite(client, model, cap, step, tracer)
    return cap, step


def _rewrite(client, model: str, cap: dict, step: dict, tracer) -> str:
    """The text-only call that writes the prose from the confirmed Claims. Only its text is
    used: the Claims stay the ones the verifier kept."""
    import json

    claims = {"objects": cap["objects"], "relations": cap["relations"]}
    prompt = REWRITE_PROMPT.format(text=cap["text"], claims=json.dumps(claims))
    request = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "toolConfig": {"tools": [CAPTION_TOOL], "toolChoice": {"tool": {"name": "submit_caption"}}},
        "inferenceConfig": {"maxTokens": 800},
    }
    if tracer is None:
        resp = client.converse(**request)
    else:
        recorded = {"prompt": prompt, "tools": ["submit_caption"],
                    "tool_choice": "submit_caption", "max_tokens": 800}  # fmt: skip
        resp = tracer.converse(client, "llm", "rewrite", request, recorded,
                               {"expects_tool": "submit_caption"})  # fmt: skip
    for k, v in resp.get("usage", {}).items():
        if isinstance(v, int):
            step["usage"][k] = step["usage"].get(k, 0) + v
    blocks = resp["output"]["message"]["content"]
    submitted = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
    if submitted is None or not submitted.get("text"):
        raise HarnessFault(f"{model} didn't rewrite the verified Caption", step)
    return submitted["text"]


def _draft(
    client,
    model: str,
    chip_id: str,
    png: bytes,
    prompt_template: str = PROMPT,
    tracer=None,
    image_key: str | None = None,
    toolbox=None,
    max_turns: int = MAX_TURNS,
    ontology_context: str | None = None,
) -> tuple[dict, dict]:
    """Caption one Chip. Returns the Caption (minus `case_id`) and a summary of the call.

    `prompt_template` may use {grid}, {objects}, and {relations}. `ontology_context`, when given,
    is appended as class-level guidance (ADR-0010). With a `tracer`, the call is recorded as a
    Step in the Run's Trace: the full prompt and response, the image by key and hash, timing,
    tokens, and retries. With a `toolbox` that has tools, the model may call them first (see the
    module docstring).
    """
    from clayzer.trace import image_ref

    prompt = prompt_template.format(
        grid=", ".join(GRID), objects=", ".join(OBJECTS), relations=", ".join(RELATIONS)
    )
    if ontology_context:
        prompt = f"{prompt}\n{ontology_context}"
    if toolbox is not None and toolbox.specs:
        ref = image_ref(image_key or f"chips/{chip_id}.png", png)
        return _with_tools(client, model, chip_id, png, prompt, tracer, ref, toolbox, max_turns)
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
        "toolConfig": {"tools": [CAPTION_TOOL], "toolChoice": {"tool": {"name": "submit_caption"}}},
        "inferenceConfig": {"maxTokens": 1500},
    }
    started = time.monotonic()
    if tracer is None:
        resp = client.converse(**request)
    else:
        recorded = {
            "prompt": prompt,
            "image": image_ref(image_key or f"chips/{chip_id}.png", png),
            "tools": ["submit_caption"],
            "tool_choice": "submit_caption",
            "max_tokens": 1500,
        }
        resp = tracer.converse(
            client, "llm", "caption", request, recorded, {"expects_tool": "submit_caption"}
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


def _with_tools(client, model, chip_id, png, prompt, tracer, image, toolbox, max_turns):
    """The tool-use loop. The model chooses when to call tools (toolChoice auto: Opus 5.5
    rejects a forced choice), and the Run ends at its `submit_caption` call."""
    specs = [CAPTION_TOOL] + [
        {"toolSpec": {"name": t.name, "description": t.description or t.name,
                      "inputSchema": {"json": t.input_schema}}}
        for t in toolbox.specs
    ]  # fmt: skip
    names = [t["toolSpec"]["name"] for t in specs]
    messages = [{"role": "user", "content": [
        {"image": {"format": "png", "source": {"bytes": png}}},
        {"text": prompt + TOOLS_NOTE},
    ]}]  # fmt: skip
    usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    calls, started = 0, time.monotonic()

    def summary(turn: int, stop_reason, ok: bool, exhausted: bool = False) -> dict:
        step = {
            "step": "caption", "chip_id": chip_id, "model": model,
            "seconds": round(time.monotonic() - started, 2), "usage": dict(usage),
            "stop_reason": stop_reason, "ok": ok, "turns": turn, "tool_calls": calls,
        }  # fmt: skip
        if tracer is not None:
            tracer.run.tools = names
            tracer.run.metadata["turn_budget"] = {"max_turns": max_turns, "turns": turn,
                                                  "exhausted": exhausted}  # fmt: skip
        return step

    for turn in range(1, max_turns + 1):
        request = {
            "modelId": model,
            "messages": messages,
            "toolConfig": {"tools": specs, "toolChoice": {"auto": {}}},
            "inferenceConfig": {"maxTokens": 1500},
        }
        if tracer is None:
            resp = client.converse(**request)
        else:
            # The first turn records the prompt and image; later turns add only tool results,
            # which are already in the Trace as tool Steps.
            recorded = {"turn": turn, "tools": names, "tool_choice": "auto", "max_tokens": 1500}
            if turn == 1:
                recorded |= {"prompt": prompt + TOOLS_NOTE, "image": image}
            resp = tracer.converse(client, "llm", "caption", request, recorded,
                                   {"expects_tool": "submit_caption", "turn": turn})  # fmt: skip
        for k in usage:
            usage[k] += resp.get("usage", {}).get(k, 0) or 0
        blocks = resp["output"]["message"]["content"]
        uses = [b["toolUse"] for b in blocks if "toolUse" in b]
        submitted = next((u["input"] for u in uses if u["name"] == "submit_caption"), None)
        if submitted is not None:
            return _clean(submitted), summary(turn, resp.get("stopReason"), True)
        if not uses:
            step = summary(turn, resp.get("stopReason"), False)
            raise HarnessFault(
                f"{model} stopped without calling submit_caption for {chip_id}", step
            )

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for use in uses:
            t0 = time.time()
            r = toolbox.call(use["name"], use.get("input") or {})
            calls += 1
            if tracer is not None:
                tracer.tool(use["name"], use.get("input") or {}, t0, time.time(), r.text,
                            r.text[:1000] if r.is_error else None, {
                                "tool_use_id": use["toolUseId"],
                                "server": toolbox.server_for(use["name"]),
                                "is_error": r.is_error, "error_code": r.error_code,
                                "truncated": len(r.text) > MAX_TOOL_TEXT,
                            })  # fmt: skip
            results.append({"toolResult": {
                "toolUseId": use["toolUseId"],
                "content": [{"text": r.text[:MAX_TOOL_TEXT] or "(no output)"}],
                "status": "error" if r.is_error else "success",
            }})  # fmt: skip
        messages.append({"role": "user", "content": results})

    step = summary(max_turns, "turn_budget", False, exhausted=True)
    raise HarnessFault(
        f"{model} used its {max_turns}-turn budget without calling submit_caption for {chip_id}",
        step,
    )


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
