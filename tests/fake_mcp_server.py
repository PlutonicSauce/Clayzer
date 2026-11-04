"""A stdio MCP server for the agentic Harness tests: one tool that works, one that fails."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("fake")


@server.tool()
def lookup(place: str) -> str:
    """Say which imagery covers a place."""
    return f"NAIP 2022 covers {place}"


@server.tool()
def broken() -> str:
    """Always fails."""
    raise ValueError("boom")


if __name__ == "__main__":
    server.run()
