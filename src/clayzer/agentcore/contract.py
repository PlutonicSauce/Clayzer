"""The Run contract: what a Batch sends an AgentCore Runtime for one Run, and what comes back.

The contract is where the project's rules meet the network, so it is strict on purpose:

- ADR-0006, Answer Keys stay hidden. A request has a fixed set of fields and no room for a
  Case's Reference Labels. An unknown field is refused, so a label can't ride along, and the
  Runtime role has no access to the store, so it couldn't read one either.
- The allowlist applies. The tool servers a request names are checked against allowlist.py on
  both sides: before the Batch sends it, and again inside the Runtime.
- ADR-0009, only the verifier sees the footprint: it is for the code that verifies Claims, and
  the model is never given it.
- ADR-0001, the Trace is ours. The Runtime returns every Step in full, and the Batch writes the
  Trace, so there is one writer and replay needs nothing from AgentCore.
- ADR-0003, faults. An error comes back with a kind, so the Batch can tell the Harness's fault
  (the model didn't submit a Caption) from the environment's (Bedrock throttled, a sign-in is
  missing).

Plain dataclasses and JSON, so the Runtime image needs nothing beyond what the Harness does.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from clayzer import allowlist

# Bump when a field's meaning changes. A Runtime and a Batch on different versions refuse each
# other, rather than score the wrong thing.
CONTRACT_VERSION = 1

# Error kinds a response can carry, and how the Batch treats each (remote.py).
HARNESS_FAULT = "harness_fault"  # the model gave no usable Caption: the system under test's fault
BEDROCK = "bedrock"  # a Bedrock call failed: the environment's fault, no valid score
NOT_SIGNED_IN = "not_signed_in"  # a tool server's sign-in is missing
CONTRACT = "contract"  # the request broke the contract: a mismatch to fix, not a Run to retry
INTERNAL = "internal"  # the Runtime itself failed


class ContractError(ValueError):
    """A request the Runtime must not run."""


@dataclass(frozen=True)
class RunRequest:
    contract: int
    chip_id: str
    image_b64: str  # the Chip's PNG; its SHA-256 is checked on arrival
    image_sha256: str
    image_key: str  # chips/<id>.png: how the Trace names the image
    prompt: str
    model: str
    max_turns: int
    tools: list[str] = field(default_factory=list)  # MCP servers the model may use
    verify: str | None = None  # the MCP server that verifies Claims
    footprint: dict | None = None  # {"bbox": [...], "date": ...}: for the verifier only

    @classmethod
    def build(cls, *, chip: dict, png: bytes, prompt: str, model: str, max_turns: int,
              tools: list[str], verify: str | None, footprint: dict | None) -> RunRequest:  # fmt: skip
        """The request for one Chip. It takes the Chip, never the Case, so there is nothing
        from the Case's Reference Labels to send."""
        request = cls(
            contract=CONTRACT_VERSION, chip_id=chip["id"],
            image_b64=base64.b64encode(png).decode(),
            image_sha256=hashlib.sha256(png).hexdigest(), image_key=chip["uri"],
            prompt=prompt, model=model, max_turns=max_turns, tools=list(tools),
            verify=verify, footprint=footprint,
        )  # fmt: skip
        request.check()
        return request

    def check(self) -> None:
        """Refuse a request that breaks a rule. Run on both sides of the wire."""
        if self.contract != CONTRACT_VERSION:
            raise ContractError(
                f"contract version {self.contract}, but this side speaks {CONTRACT_VERSION}"
            )
        allowlist.check_names([*self.tools, *([self.verify] if self.verify else [])])
        if not self.image_key.startswith("chips/"):
            raise ContractError(f"the image key must be a chips/ key: {self.image_key}")
        if self.max_turns < 1:
            raise ContractError("max_turns must be at least 1")
        if self.footprint is not None and not {"bbox", "date"} >= set(self.footprint):
            raise ContractError("the footprint holds only a bbox and a date")

    def png(self) -> bytes:
        png = base64.b64decode(self.image_b64, validate=True)
        if hashlib.sha256(png).hexdigest() != self.image_sha256:
            raise ContractError("the image does not match its SHA-256: damaged in transit")
        return png

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode()

    @classmethod
    def from_json(cls, raw: bytes | str) -> RunRequest:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ContractError(f"the request is not JSON: {e}") from None
        if not isinstance(data, dict):
            raise ContractError("the request must be a JSON object")
        known = {f.name for f in fields(cls)}
        extra = sorted(set(data) - known)
        if extra:  # the door a Reference Label would come through (ADR-0006)
            raise ContractError(f"unknown field(s) {extra}: the Run contract has a fixed set")
        required = {"contract", "chip_id", "image_b64", "image_sha256", "image_key", "prompt",
                    "model", "max_turns"}  # fmt: skip
        missing = sorted(required - set(data))
        if missing:
            raise ContractError(f"missing field(s) {missing}")
        request = cls(**data)
        request.check()
        return request


@dataclass
class RunResponse:
    contract: int = CONTRACT_VERSION
    caption: dict | None = None
    step: dict | None = None  # the Harness's summary of the call: seconds, usage, turns
    steps: list[dict] = field(default_factory=list)  # the Trace's Steps, in full
    tools: list[str] = field(default_factory=list)  # names of the tools offered to the model
    metadata: dict = field(default_factory=dict)  # turn budget, verification report
    tool_versions: dict = field(default_factory=dict)  # what each MCP server reported
    build: str | None = None  # which build of the Runtime image answered
    error: dict | None = None  # {"kind", "code", "message"}; the Caption may then be missing

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), default=str).encode()

    @classmethod
    def from_json(cls, raw: bytes | str) -> RunResponse:
        data: dict[str, Any] = json.loads(raw)
        if data.get("contract") != CONTRACT_VERSION:
            raise ContractError(
                f"the Runtime answered contract {data.get('contract')}, expected {CONTRACT_VERSION}"
            )
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @staticmethod
    def failure(kind: str, code: str, message: str, **rest) -> RunResponse:
        return RunResponse(error={"kind": kind, "code": code, "message": message[:1000]}, **rest)
