"""A stdio stand-in for LGND Geo's two verification tools: it confirms solar and nothing else."""

import json

from mcp.server.mcpserver import MCPServer

server = MCPServer("fake-lgnd")


@server.tool()
def search_chip_lat_lon(index: str, lat: float, lon: float) -> str:
    """The newest chip at a point."""
    return json.dumps({"node": f"{index}/obs:{lat:.4f},{lon:.4f}", "observed": "2022-07-02"})


@server.tool()
def reasoning_imagery_check(claim: str, kind: str, nodes: list[str]) -> str:
    """Check a claim against the imagery of the places it cites."""
    ok = "solar" in claim.lower()
    return json.dumps({
        "verdict": "supported" if ok else "not supported",
        "supported_at": nodes if ok else [],
        "places": {"columns": ["node", "answer", "reason"],
                   "rows": [[nodes[0], "yes" if ok else "no",
                             "panels in rows" if ok else "no such thing here"]]},
    })  # fmt: skip


if __name__ == "__main__":
    server.run()
