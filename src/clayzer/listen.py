"""A spoken summary of a Batch's result: what it scored, how that compares with the Baseline, and
the regression gate's verdict, as an MP3 anyone on the team can listen to.

Code computes the facts from the stored Batch and the gate, so the numbers are never a model's.
A model (Nova Pro) turns them into a short script for the ear, and Amazon Polly reads it aloud.
A script that states a number the facts don't have is rejected, and the code-written script is
used instead; it's also the fallback when Bedrock isn't reachable.

The MP3 and its script are saved next to the Batch with a hash of the facts they were made from.
The web app only plays the saved file, so the hosted, read-only app never calls Bedrock or Polly
(REQ-09). Running `clayzer listen` again rewrites them only when the facts changed, for example
after a rescore or a new Baseline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime

from clayzer import batch as batches

DEFAULT_VOICE = "Ruth"
DEFAULT_ENGINE = "generative"
MAX_SCRIPT_CHARS = 1500  # Polly takes 3,000 characters per call; a minute of speech is ~900
METRICS = {
    "correctness": "correctness, how much of what the captions claim is right",
    "coverage": "coverage, how much of what's really there the captions mention",
    "fidelity": "fidelity, the Judge's rating of each caption against its image",
}
_CASE_ID = re.compile(r"(fixed|change)-[a-z]+-([a-z]+)(?:-(\d+))?")
_KINDS = {"uspvdb": "solar site", "uswtdb": "wind site", "neg": "negative site"}

SYSTEM = """You write a short spoken summary of one evaluation Batch of an AI captioner that
describes aerial images. It will be read aloud by a text-to-speech voice to people on the team who
want the result without reading a report.

Write 4 to 7 plain sentences, under 120 words, as one paragraph:
1. What was tested: how many places, how many times each.
2. The headline: the regression gate's verdict and what it means (pass: nothing got worse, so the
   change can be kept; fail: something got worse; inconclusive: the result can't be trusted yet).
3. The scores that matter, as whole numbers out of 100, and how they moved against the Baseline.
4. Why it failed or was inconclusive, if it did, in everyday words. Name at most two places.
5. One sentence on what to do next.

Rules: it's for the ear, so no markdown, lists, symbols, abbreviations, or IDs with dashes. Say
"out of 100", not "percent". Use only numbers that appear in the facts below, and don't add any
judgment the facts don't support."""


# ── Facts, by code ──────────────────────────────────────────────────────────────────────


def spoken_case(case_id: str) -> str:
    """A Case id as words: fixed-dev-uspvdb-400117 is "the solar site 400117"."""
    m = _CASE_ID.fullmatch(case_id)
    if not m:
        return case_id.replace("-", " ")
    kind = _KINDS.get(m[2], f"{m[2]} site")
    pair = " image pair" if m[1] == "change" else ""
    return f"the {kind}{pair} number {m[3]}" if m[3] else f"the {kind}{pair}"


def _pts(x: float | None) -> int | None:
    return None if x is None else round(x * 100)


def facts(b: dict, baseline: dict | None, gate_result=None) -> dict:
    """Everything the summary may say, computed from the stored Batch and its gate result."""
    cfg, s = b["config"], b["summary"] or {}
    batch = s.get("batch") or {}
    out: dict = {
        "batch_id": cfg.batch_id,
        "label": cfg.label,
        "cases": len(cfg.case_ids),
        "repeats": cfg.repeats,
        "runs": batch.get("runs") or {},
        "scores": {k: _pts(batch.get(k)) for k in METRICS},
        "retrieval_top1": _pts((batch.get("retrieval_recall_at_1") or {}).get("mean")),
        "stopped": s.get("stopped"),
    }
    per_case = s.get("cases") or {}
    ranked = sorted(
        (c for c in per_case.items() if c[1]["correctness"]["mean"] is not None),
        key=lambda c: c[1]["correctness"]["mean"],
    )
    out["weakest"] = [{"case": spoken_case(cid), "correctness": _pts(c["correctness"]["mean"])}
                      for cid, c in ranked[:2]]  # fmt: skip
    if baseline is None:
        out["baseline"] = None
        return out
    bb = baseline["summary"]["batch"]
    out["baseline"] = {
        "batch_id": baseline["config"].batch_id,
        "is_this_batch": baseline["config"].batch_id == cfg.batch_id,
        "scores": {k: _pts(bb.get(k)) for k in METRICS},
    }
    out["change"] = {k: None if out["scores"][k] is None or out["baseline"]["scores"][k] is None
                     else out["scores"][k] - out["baseline"]["scores"][k] for k in METRICS}  # fmt: skip
    # Gating the Baseline against itself says nothing, so there's no verdict to speak.
    if gate_result is not None and not out["baseline"]["is_this_batch"]:
        regressed = sorted({c.case_id for c in gate_result.checks if c.status == "regressed"})
        improved = sorted({c.case_id for c in gate_result.checks if c.status == "improved"}
                          - set(regressed))  # fmt: skip
        out["gate"] = {
            "verdict": gate_result.verdict,
            "reasons": gate_result.reasons,
            "warnings": gate_result.warnings,
            "regressed_cases": [spoken_case(c) for c in regressed],
            "improved_cases": len(improved),
        }
    return out


def facts_sha(f: dict) -> str:
    return hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:16]


# ── The script ──────────────────────────────────────────────────────────────────────────


def _moved(delta: int | None) -> str:
    if not delta:
        return "unchanged"
    return f"up {delta}" if delta > 0 else f"down {-delta}"


def code_script(f: dict) -> str:
    """The summary written by code: the fallback, and what the model's version is checked
    against. Always the same for the same facts."""
    times = "once" if f["repeats"] == 1 else f"{f['repeats']} times"
    say = [f"This Batch captioned {f['cases']} places, {times} each."]
    gate = f.get("gate")
    base = f.get("baseline")
    if f["stopped"]:
        say.append("It stopped before every Run finished, so treat these scores as partial.")
    if gate and not base["is_this_batch"]:
        say.append({
            "pass": "It passed the regression gate: nothing got worse than the Baseline, so the "
                    "change can be kept.",
            "fail": "It failed the regression gate: something got worse than the Baseline.",
            "inconclusive": "The regression gate was inconclusive, so the result can't be "
                            "trusted yet.",
        }[gate["verdict"]])  # fmt: skip
    elif base and base["is_this_batch"]:
        say.append("It is the current Baseline, so there's nothing to compare it with.")
    else:
        say.append("There's no Baseline to compare it with yet.")
    parts = []
    for k in METRICS:
        v = f["scores"][k]
        if v is None:
            continue
        part = f"{k} {v} out of 100"
        if base and not base["is_this_batch"] and f["change"][k] is not None:
            part += f", {_moved(f['change'][k])}"
        parts.append(part)
    if parts:
        say.append("Scores: " + "; ".join(parts) + ".")
    if gate and gate["regressed_cases"]:
        names = gate["regressed_cases"]
        more = f", and {len(names) - 2} more" if len(names) > 2 else ""
        say.append("Scores dropped at " + " and ".join(names[:2]) + more + ".")
    elif gate and gate["reasons"] and gate["verdict"] != "pass" and not base["is_this_batch"]:
        say.append("The gate's reason: " + _plain(gate["reasons"][0]) + ".")
    elif f["weakest"]:
        w = f["weakest"][0]
        say.append(f"The weakest place was {w['case']}, at {w['correctness']} out of 100 "
                   "for correctness.")  # fmt: skip
    if gate and not base["is_this_batch"]:
        say.append({
            "pass": "Next, accept it as the new Baseline if the change is worth keeping.",
            "fail": "Next, open the report and look at the Cases that dropped.",
            "inconclusive": "Next, resume or rerun the Batch, then gate it again.",
        }[gate["verdict"]])  # fmt: skip
    return " ".join(say)


def _plain(reason: str) -> str:
    """A gate reason with Case ids turned into words and commands dropped."""
    reason = re.sub(r"`[^`]*`", "", reason)
    reason = _CASE_ID.sub(lambda m: spoken_case(m[0]), reason)
    return reason.replace(";", ",").strip(" ,.")


def digest(f: dict) -> str:
    """The facts as text: everything the model is given."""
    return (
        "## Facts\n"
        + json.dumps(f, indent=2)
        + "\n\n## A plain version written by code\n"
        + code_script(f)
    )


def unsupported_numbers(script: str, f: dict) -> list[str]:
    """Numbers the script states that the facts don't contain: grounds to reject it."""
    allowed = set(re.findall(r"\d+", digest(f))) | {"100"}
    return sorted(set(re.findall(r"\d+", script)) - allowed)


def model_script(client, model: str, f: dict) -> dict:
    started = time.monotonic()
    resp = client.converse(
        modelId=model,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": digest(f)}]}],
        inferenceConfig={"maxTokens": 400, "temperature": 0.3},
    )
    blocks = resp["output"]["message"]["content"]
    text = " ".join(" ".join(b["text"] for b in blocks if "text" in b).split())
    return {"text": text, "model": model, "usage": resp.get("usage", {}),
            "seconds": round(time.monotonic() - started, 2)}  # fmt: skip


def write_script(client, f: dict, progress=print) -> dict:
    """The model's script when it's usable, else the code-written one."""
    from clayzer.narrate import summary_model

    if client is not None:
        try:
            out = model_script(client, summary_model(), f)
        except Exception as e:  # noqa: BLE001 -- the code-written script is the fallback
            progress(
                f"  spoken script: model failed ({type(e).__name__}); using the code-written one"
            )
        else:
            bad = unsupported_numbers(out["text"], f)
            if not out["text"] or len(out["text"]) > MAX_SCRIPT_CHARS:
                progress(
                    "  spoken script: model's script empty or too long; using the code-written one"
                )
            elif bad:
                progress(f"  spoken script: model stated {', '.join(bad)}, not in the facts; "
                         "using the code-written one")  # fmt: skip
            else:
                return {**out, "source": "model"}
    return {"text": code_script(f), "source": "code", "model": None}


# ── The audio ───────────────────────────────────────────────────────────────────────────


def polly():
    import boto3

    return boto3.client("polly")


def voice() -> tuple[str, str]:
    return (os.environ.get("CLAYZER_VOICE", DEFAULT_VOICE),
            os.environ.get("CLAYZER_VOICE_ENGINE", DEFAULT_ENGINE))  # fmt: skip


def synthesize(client, text: str, voice_id: str, engine: str) -> bytes:
    resp = client.synthesize_speech(
        Text=text, VoiceId=voice_id, Engine=engine, OutputFormat="mp3", TextType="text"
    )
    return resp["AudioStream"].read()


# ── The Batch ───────────────────────────────────────────────────────────────────────────


def script_key(batch_id: str) -> str:
    return f"batches/{batch_id}/listen.json"


def audio_key(batch_id: str) -> str:
    return f"batches/{batch_id}/listen.mp3"


def listen(store, batch_id: str, baseline: dict | None, bedrock_client, polly_client,
           force: bool = False, progress=print) -> dict:  # fmt: skip
    """Write the Batch's spoken summary, unless one from the same facts is already saved.
    Returns the saved record, with "written" true when it was (re)made."""
    from clayzer.gate import gate

    b = batches.load(store, batch_id)
    if b["summary"] is None:
        raise ValueError(f"Batch {batch_id} has no summary yet; finish or resume it first")
    result = None
    if baseline is not None:
        try:
            result = gate(baseline, b)
        except ValueError as e:
            progress(f"  spoken script: no gate verdict ({e})")
    f = facts(b, baseline, result)
    sha = facts_sha(f)
    skey, akey = script_key(batch_id), audio_key(batch_id)
    if not force and store.exists(skey) and store.exists(akey):
        saved = json.loads(store.get(skey))
        if saved.get("facts_sha") == sha:
            return {**saved, "written": False}
    script = write_script(bedrock_client, f, progress)
    voice_id, engine = voice()
    audio = synthesize(polly_client, script["text"], voice_id, engine)
    record = {
        "batch_id": batch_id,
        "text": script["text"],
        "source": script["source"],
        "model": script["model"],
        "usage": script.get("usage", {}),
        "voice": voice_id,
        "engine": engine,
        "baseline_id": (f.get("baseline") or {}).get("batch_id"),
        "verdict": (f.get("gate") or {}).get("verdict"),
        "facts": f,
        "facts_sha": sha,
        "audio_bytes": len(audio),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    store.put(akey, audio, "audio/mpeg")
    store.put(skey, (json.dumps(record, indent=2) + "\n").encode(), "application/json")
    return {**record, "written": True}


def after_batch(store, settings, batch_id: str, baseline_name: str = "default",
                progress=print) -> dict | None:  # fmt: skip
    """The spoken summary for a Batch that just finished. Anything that goes wrong is reported
    and skipped: a missing summary never fails a Batch, and `clayzer listen` can make it later."""
    from clayzer.gate import load_baseline

    try:
        try:
            base = load_baseline(settings.baselines_dir, baseline_name)
        except FileNotFoundError:
            base = None
        rec = listen(store, batch_id, base, batches.bedrock(settings), polly(), progress=progress)
    except Exception as e:  # noqa: BLE001 -- see the docstring
        progress(f"spoken summary skipped ({type(e).__name__}: {str(e)[:160]}); "
                 f"make it later with `clayzer listen {batch_id}`")  # fmt: skip
        return None
    progress(f"spoken summary: {store.url(audio_key(batch_id))}")
    return rec
