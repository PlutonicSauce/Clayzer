"""Blind human calibration export/import; never generate human answers or change the rubric."""

import math

from clayzer.judge import validate_verdict
from clayzer.provenance import judge_prompt, sha


def blind_packet(rows: list[dict]) -> dict:
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Calibration ids must be unique")
    return {
        "rubric_sha": sha(judge_prompt().encode()),
        "rubric": judge_prompt(),
        "items": [{k: r.get(k) for k in ("id", "text", "image_uri")} for r in rows],
        "instructions": "Label blind, using the supplied rubric. Return id, score, issues, annotator, blind=true and rubric_sha. Do not view model verdicts.",
    }


def calibration_metrics(labels: list[dict], verdicts: dict[str, dict], rubric_sha: str) -> dict:
    pairs, seen, annotators = [], set(), set()
    for row in labels:
        identity = (row.get("id"), row.get("annotator"))
        if (
            not all(identity)
            or identity in seen
            or row.get("blind") is not True
            or row.get("rubric_sha") != rubric_sha
        ):
            raise ValueError(
                "Calibration requires unique (id, annotator), blind labels and matching rubric"
            )
        seen.add(identity)
        annotators.add(row["annotator"])
        human = validate_verdict(row)["score"]
        model = verdicts.get(row["id"])
        if model is None:
            raise ValueError("Calibration label has no corresponding model verdict")
        pairs.append((human, validate_verdict(model)["score"]))
    n = len(pairs)
    return {
        "pairs": n,
        "captions": len({r["id"] for r in labels}),
        "annotators": len(annotators),
        "mae": sum(abs(h - m) for h, m in pairs) / n if n else None,
        "rmse": math.sqrt(sum((h - m) ** 2 for h, m in pairs) / n) if n else None,
        "mean_judge_minus_human": sum(m - h for h, m in pairs) / n if n else None,
        "within_0_25": sum(abs(h - m) <= 0.25 for h, m in pairs) / n if n else None,
        "rubric_sha": rubric_sha,
        "note": "Blindness is attested by annotators; repeated ratings are not independent samples",
    }


def claim_calibration(labels: list[dict], extracted: dict[str, dict]) -> dict:
    """Exact object/count/position/attribute agreement with blind, imported human Claims.

    Missing human/model fields remain null; no tolerant match hides invented counts or cells.
    Multiple raters yield multiple pairs, not extra independent captions.
    """
    from collections import Counter

    from clayzer.extraction import VERSION, validate_claims

    def signatures(cap):
        return Counter(
            (
                o["object"],
                o.get("count"),
                o.get("position"),
                tuple(sorted(o.get("attributes", {}).items())),
            )
            for o in cap["objects"]
        )

    tp, predicted, reference, pairs, seen = 0, 0, 0, 0, set()
    for row in labels:
        key = (row.get("id"), row.get("annotator"))
        if (
            not all(key)
            or key in seen
            or row.get("blind") is not True
            or row.get("extraction_version") != VERSION
        ):
            raise ValueError(
                "Blind calibration requires unique human labels and matching extraction version"
            )
        seen.add(key)
        model = extracted.get(row["id"])
        if model is None or model.get("text") != row.get("text"):
            raise ValueError("Calibration caption source does not match")
        human = validate_claims(row["claims"], row["text"])
        hs, ms = signatures(human), signatures(model)
        tp += sum((hs & ms).values())
        predicted += sum(ms.values())
        reference += sum(hs.values())
        pairs += 1
    return {
        "pairs": pairs,
        "matching_claims": tp,
        "model_claims": predicted,
        "human_claims": reference,
        "precision": tp / predicted if predicted else None,
        "recall": tp / reference if reference else None,
        "extraction_version": VERSION,
        "note": "Exact object/count/position/attribute matches; relations require separate human review",
    }
