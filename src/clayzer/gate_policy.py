"""Explicit, versioned acceptance rules for the regression gate. No model calls."""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from clayzer import baseline_files
from clayzer.gate_evidence import METRIC_PATHS, number


@dataclass(frozen=True)
class GatePolicy:
    version: int = 1
    max_allowed_drop: float | None = None
    minimum_scores: dict[str, float] = field(default_factory=dict)
    require_improvement: bool = False
    anchor: str | None = None
    anchor_snapshot: str | None = None

    def validate(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError("gate policy version must be 1")
        number(self.max_allowed_drop, "policy max_allowed_drop", upper=1)
        if type(self.require_improvement) is not bool:
            raise ValueError("policy require_improvement must be a boolean")
        if not isinstance(self.minimum_scores, dict):
            raise ValueError("policy minimum_scores must be an object")  # noqa: TRY004 -- saved config
        for metric, value in self.minimum_scores.items():
            if metric not in {*METRIC_PATHS, "retrieval"}:
                raise ValueError(f"unknown policy score: {metric}")
            number(value, f"policy minimum {metric}", upper=1, optional=False)
        if self.anchor is not None:
            baseline_files.baseline_name(self.anchor)
            if not isinstance(self.anchor_snapshot, str) or not re.fullmatch(
                r"[0-9a-f]{64}", self.anchor_snapshot
            ):
                raise ValueError("policy anchor requires its SHA-256 anchor_snapshot")
        elif self.anchor_snapshot is not None:
            raise ValueError("policy anchor_snapshot requires an anchor")

    def to_dict(self):
        self.validate()
        return asdict(self)


def _unique_fields(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate gate policy field: {key}")
        data[key] = value
    return data


def load_policy(path: Path | None) -> GatePolicy | None:
    if path is None:
        return None
    data = json.loads(path.read_text(), object_pairs_hook=_unique_fields)
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError("gate policy must be an object with version=1")
    unknown = set(data) - set(GatePolicy.__dataclass_fields__)
    if unknown:
        raise ValueError("unknown gate policy fields: " + ", ".join(sorted(unknown)))
    policy = GatePolicy(**data)
    policy.validate()
    return policy
