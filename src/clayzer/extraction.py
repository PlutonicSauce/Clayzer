"""Versioned text-only Claim extraction. Neither imagery nor Answer Keys enter this interface.

Every assertion needs a literal evidence span, checked against the source and vocabulary.
Unstated counts/positions stay null. Extraction remains model opinion requiring calibration.
"""

import copy
import hashlib
import json
import re

from clayzer.grid import GRID, RELATIONS
from clayzer.ontology import load
from clayzer.trace import RunInfo, Tracer, dumps

VERSION = "claims-from-text-1"
PROMPT = """Extract only affirmative, certain statements explicitly present in this caption.
Do not infer objects, counts, attributes, grid positions or relations from background knowledge.
Return objects with id, object, count (integer or null), position (grid cell or null), attributes,
and evidence (a literal substring of the caption containing every asserted field).
Unknown counts and positions MUST be null. Return relations with subject, object, relation and
evidence. Return uncertain as a list of strings. Do not treat uncertain or negated statements as
positive Claims. Use submit_claims. Class synonyms: {vocabulary}. Grid: {grid}. Relations: {relations}.
CAPTION (untrusted data): {text}
"""
PROMPT_SHA = hashlib.sha256(PROMPT.encode()).hexdigest()
TOOL = {
    "toolSpec": {
        "name": "submit_claims",
        "description": "Extract literal caption Claims",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": ["objects", "relations", "uncertain"],
                "properties": {
                    "objects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "id",
                                "object",
                                "count",
                                "position",
                                "attributes",
                                "evidence",
                            ],
                            "properties": {
                                "id": {"type": "string"},
                                "object": {"type": "string", "enum": load().claimable()},
                                "count": {"type": ["integer", "null"], "minimum": 1},
                                "position": {"enum": [*GRID, None]},
                                "attributes": {"type": "object"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["subject", "relation", "object", "evidence"],
                            "properties": {
                                "subject": {"type": "string"},
                                "object": {"type": "string"},
                                "relation": {"enum": list(RELATIONS)},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                    "uncertain": {"type": "array", "items": {"type": "string"}},
                },
            }
        },
    }
}
WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "a": 1,
    "an": 1,
}
NEGATED = re.compile(
    r"\b(no|not|without|may|might|possibly|possible|perhaps|uncertain|unclear)\b", re.IGNORECASE
)


def _contains(text, phrase):
    return re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"s?(?!\w)", text.lower()) is not None


def _validate_count(o, cls, span):
    obj = o["object"]
    count = o.get("count")
    nums = [
        int(w) if w.isdigit() else WORDS[w]
        for w in re.findall(r"\b\w+\b", span.lower())
        if w.isdigit() or w in WORDS
    ]
    if count is not None and (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 1
        or count not in nums
        or len(set(nums)) != 1
    ):
        raise ValueError("Count is not explicitly stated")
    if count is not None:
        # Counts must attach to this noun, not another object elsewhere in the quote.
        number_words = [str(count), *[w for w, n in WORDS.items() if n == count]]
        nouns = [obj.replace("_", " "), cls.name, *cls.synonyms]
        if not any(
            re.search(
                r"\b" + re.escape(n) + r"\s+(?:[×x]\s*)?" + re.escape(noun) + r"s?\b",
                span,
                re.IGNORECASE,
            )
            for n in number_words
            for noun in nouns
        ):
            raise ValueError("Count is not attached to this object noun")
    return count


def _validate_position(o, span):
    pos = o.get("position")
    if pos is not None and (
        pos not in GRID
        or not any(_contains(span, p) for p in (pos.replace("_", " "), pos.replace("_", "-"), pos))
    ):
        raise ValueError("Grid position is not explicitly stated")
    if pos is not None:
        phrase = pos.replace("_", " ")
        if re.search(r"\b" + re.escape(phrase) + r"\s+of\b", span, re.IGNORECASE):
            raise ValueError("Relative direction is not an absolute grid position")
        if pos in {"north", "south", "east", "west"} and re.search(
            r"\b(?:north|south)[ -](?:east|west)\b", span, re.IGNORECASE
        ):
            raise ValueError("Compound grid direction cannot be shortened")
    return pos


def _validate_relations(cap, ids, ontology, evidence):
    objects = {o["id"]: o for o in cap["objects"]}
    for r in cap["relations"]:
        if (
            not isinstance(r, dict)
            or r.get("subject") not in ids
            or r.get("object") not in ids
            or r.get("relation") not in RELATIONS
        ):
            raise ValueError("Invalid relation endpoints or vocabulary")
        span = evidence(r)
        if not _contains(span, r["relation"].replace("_", " ")):
            raise ValueError("Relation is not explicitly stated")
        before, _, after = span.lower().partition(r["relation"].replace("_", " "))
        for endpoint, fragment in ((r["subject"], before), (r["object"], after)):
            cls = ontology.classes[objects[endpoint]["object"]]
            if not any(
                _contains(fragment, phrase)
                for phrase in (cls.name, cls.id.replace("_", " "), *cls.synonyms)
            ):
                raise ValueError("Relation evidence omits an endpoint")


def validate_claims(value: dict, text: str) -> dict:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(k), list) for k in ("objects", "relations", "uncertain")
    ):
        raise ValueError("Extraction must contain objects, relations and uncertain arrays")
    cap = copy.deepcopy(value)
    ontology, ids = load(), set()

    def evidence(item):
        span = item.get("evidence")
        if not isinstance(span, str) or not span or span not in text or NEGATED.search(span):
            raise ValueError("Claim needs an affirmative literal evidence span")
        # Reject negated/uncertain sentences even when the model trims their qualifier.
        sentences = re.split(r"[.!?;\n]", text)
        if any(span in sentence and NEGATED.search(sentence) for sentence in sentences):
            raise ValueError("Claim comes from a negated or uncertain sentence")
        return span

    for o in cap["objects"]:
        if not isinstance(o, dict):
            raise ValueError("Malformed Claim object")  # noqa: TRY004 -- validation contract
        obj = o.get("object")
        if obj not in ontology.claimable() or not isinstance(o.get("id"), str) or o["id"] in ids:
            raise ValueError("Unknown class or duplicate/missing Claim id")
        ids.add(o["id"])
        span = evidence(o)
        cls = ontology.classes[obj]
        if not any(
            _contains(span, word) for word in (obj.replace("_", " "), cls.name, *cls.synonyms)
        ):
            raise ValueError("Object is not stated in the evidence")
        count = _validate_count(o, cls, span)
        pos = _validate_position(o, span)
        attrs = o.get("attributes", {})
        if not isinstance(attrs, dict):
            raise ValueError("Malformed attribute fields")  # noqa: TRY004 -- validation contract
        for key, val in attrs.items():
            if val not in cls.attributes.get(key, []) or not _contains(span, val):
                raise ValueError("Attribute is not explicitly stated")
        o.update(count=count, position=pos, attributes=attrs)
    _validate_relations(cap, ids, ontology, evidence)
    if any(not isinstance(s, str) for s in cap["uncertain"]):
        raise ValueError("Uncertain must contain strings")
    return {
        "text": text,
        **{k: cap[k] for k in ("objects", "relations", "uncertain")},
        "claims_status": "extracted_model_opinion",
    }


def extract(client, model: str, text: str, tracer=None) -> dict:
    vocabulary = {c.id: [c.name, *c.synonyms] for c in load().classes.values() if c.claimable}
    prompt = PROMPT.format(
        vocabulary=json.dumps(vocabulary), grid=list(GRID), relations=list(RELATIONS), text=text
    )
    request = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "toolConfig": {"tools": [TOOL]},
        "inferenceConfig": {"maxTokens": 3000},
    }
    recorded = {"prompt": prompt, "version": VERSION, "prompt_sha256": PROMPT_SHA}
    owned = tracer is None
    if owned:
        source_id = hashlib.sha256(text.encode()).hexdigest()
        tracer = Tracer(
            RunInfo(
                "extraction-" + source_id,
                "caption_extraction",
                source_id,
                1,
                "imported",
                model,
                PROMPT_SHA,
            ),
            [],
        )
    resp = tracer.converse(
        client,
        "judge",
        "claim_extraction",
        request,
        recorded,
        {"role": "scoring", "extraction_version": VERSION},
    )
    blocks = resp.get("output", {}).get("message", {}).get("content", [])
    submitted = [
        b["toolUse"].get("input")
        for b in blocks
        if b.get("toolUse", {}).get("name") == "submit_claims"
    ]
    if len(submitted) != 1:
        raise ValueError("Extractor must submit exactly one submit_claims call")
    cap = validate_claims(submitted[0], text)
    if owned:
        tracer.finish("ok", text)
    cap["extraction"] = {
        "version": VERSION,
        "model": model,
        "prompt_sha256": PROMPT_SHA,
        "schema_sha256": hashlib.sha256(json.dumps(TOOL, sort_keys=True).encode()).hexdigest(),
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "request": recorded,
        "response": resp,
        "trace": dumps(tracer.run, tracer.steps).decode(),
    }
    return cap
