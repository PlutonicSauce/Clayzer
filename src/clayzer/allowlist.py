"""The ADR-0006 tool list, enforced in code.

No tool the caption Harness can call may read an Answer Key (USGS, GRW, OSM) for the region being
scored, or grounding becomes circular: the Harness would score well by copying. caption-plan.md §3
lists the MCP servers that are allowed and forbidden. This module is the one place that list lives
as code, so every route that can attach a tool to a Harness asks the same question:

- `Toolbox` (tools.py) checks every server it is given, so a forbidden server can't be connected
- a Batch checks its servers before it writes anything (batch.create), so it refuses to start
- an AgentCore Runtime checks the tool list it is sent (agentcore/contract.py)
- the Workflow Score checks the tools a Run actually called (workflow.py), as a last check on
  what really happened

A server counts as forbidden when its name, URL, command, or package names one of the Answer Key
sources. Words are matched whole, not as substrings, so `cosmos` is not mistaken for `osm`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clayzer.tools import McpServer

# Sources the Answer Keys come from, or that serve the same map data. Matched as whole words,
# except the longer ones also match as a prefix (`overturemaps`, `openstreetmap-mcp-server`).
FORBIDDEN = ("openstreetmap", "osm", "nominatim", "overture")
_PREFIX_FROM = 7  # words at least this long also match as a word prefix


class ForbiddenServer(ValueError):
    """A tool server that would let the Harness read an Answer Key (ADR-0006)."""


def _words(*texts: str | None) -> list[str]:
    return [w for t in texts if t for w in re.split(r"[^a-z0-9]+", t.lower()) if w]


def forbidden_word(*texts: str | None) -> str | None:
    """The forbidden source named in any of the texts, or None."""
    for word in _words(*texts):
        for bad in FORBIDDEN:
            if word == bad or (len(bad) >= _PREFIX_FROM and word.startswith(bad)):
                return bad
    return None


def is_forbidden(*texts: str | None) -> bool:
    return forbidden_word(*texts) is not None


def _refuse(what: str, bad: str) -> ForbiddenServer:
    return ForbiddenServer(
        f"{what} would let the Harness read {bad!r} data, which holds the Answer Keys "
        "(ADR-0006, caption-plan.md §3). Use a source we don't score against."
    )


def check_names(names: list[str]) -> None:
    """Raise ForbiddenServer if any server name is on the forbidden list."""
    for name in names:
        if bad := forbidden_word(name):
            raise _refuse(f"MCP server {name!r}", bad)


def check_server(server: McpServer) -> None:
    """Raise ForbiddenServer if a server's name, URL, package, or entry point is on the list.

    Arguments are checked too, except file paths: a server started from a folder that happens to
    be called `osm` is not an OSM server."""
    args = [a for a in server.args if "/" not in a and "\\" not in a]
    texts = [server.name, server.url, server.package, server.entrypoint, *args]
    if bad := forbidden_word(*texts):
        raise _refuse(f"MCP server {server.name!r}", bad)
