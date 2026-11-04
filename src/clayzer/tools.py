"""MCP tools for the agentic Harness (REQ-01): MCP servers behind one flat set of tools.

The Harness is synchronous and a Batch runs its Runs one after another, so a Toolbox owns one
event loop on a background thread and the servers stay up for the whole Batch. Same shape as
the Sandbox's provider (breaking-barriers tools/mcp.py): servers are pinned, so the tools under
test don't change between Batches that are compared, and child servers get the full parent
environment (the SDK's default drops the AWS and uv variables they need). Servers either run
locally over stdio or are remote over HTTP; remote ones may need a sign-in (mcp_auth.py).

Only servers allowed for the caption Harness are listed (caption-plan.md §3): none may read an
Answer Key, or grounding becomes circular (ADR-0006). Needs the `tools` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Self

# Bedrock tool names: letters, digits, underscores and dashes, at most 64 characters.
_NAME_LIMIT = 64


@dataclass(frozen=True)
class McpServer:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    # For uvx-launched Python servers: the pinned package and its "module:function" entry
    # point, so the server can be relaunched with the OS trust store (see launch).
    package: str | None = None
    entrypoint: str | None = None
    # Remote servers: the streamable-HTTP endpoint, and whether it needs an OAuth sign-in.
    url: str | None = None
    oauth: bool = False

    def launch(self) -> tuple[str, list[str]]:
        """Command and args to start the server.

        With CLAYZER_MCP_SYSTEM_TRUST=1, Python servers start with `truststore` injected, so
        TLS verifies against the OS trust store. Needed behind TLS-intercepting proxies:
        servers that pass verify=True to boto3 or httpx ignore AWS_CA_BUNDLE and SSL_CERT_FILE.
        """
        if os.environ.get("CLAYZER_MCP_SYSTEM_TRUST") != "1" or not (
            self.package and self.entrypoint
        ):
            return self.command, self.args
        module, function = self.entrypoint.split(":")
        bootstrap = (
            "import truststore; truststore.inject_into_ssl(); "
            f"from {module} import {function}; {function}()"
        )
        return "uvx", [
            "--from",
            self.package,
            "--with",
            "truststore",
            "python",
            "-I",
            "-c",
            bootstrap,
        ]


def _uvx(name: str, package: str, entrypoint: str) -> McpServer:
    return McpServer(name, "uvx", [package], package, entrypoint)


SERVERS: dict[str, McpServer] = {
    # Registry of Open Data on AWS: dataset discovery and sampling. Allowed: no Answer Key data.
    "roda": _uvx("roda", "awslabs.roda-mcp-server==0.1.7", "awslabs.roda_mcp_server.server:main"),
    # LGND Geo: search, classify, and check imagery over NAIP and Sentinel-2 embeddings.
    # Allowed: it reads imagery and an image model, not OSM or USGS. Needs `clayzer login lgnd`.
    # Remote, so it can't be pinned by version; Batches record what it reported (initialize).
    "lgnd": McpServer("lgnd", url="https://geo.lgnd.ai/mcp", oauth=True),
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    server: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolResult:
    text: str
    is_error: bool
    error_code: str | None = None


class ToolView:
    """Some of a Toolbox's tools, callable like the Toolbox itself."""

    def __init__(self, box: Toolbox, specs: list[ToolSpec]):
        self.box, self.specs = box, specs

    def server_for(self, name: str) -> str | None:
        return next((s.server for s in self.specs if s.name == name), None)

    def call(self, name: str, arguments: dict, timeout: float | None = None) -> ToolResult:
        if self.server_for(name) is None:
            return ToolResult(f"unknown tool {name!r}", True, "UnknownTool")
        return self.box.call(name, arguments, timeout)


class Toolbox:
    """The tools of one or more MCP servers, callable from synchronous code.

    Use as a context manager. Tool names must be unique across the servers.
    """

    def __init__(
        self, servers: list[McpServer], call_timeout: float = 60.0, interactive: bool = False
    ):
        self.servers = servers
        self.call_timeout = call_timeout
        # Only `clayzer login` may open a browser to sign in; Batches use the saved sign-in.
        self.interactive = interactive
        self.versions: dict[str, str] = {}
        self.specs: list[ToolSpec] = []
        self._sessions: dict = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._stack: AsyncExitStack | None = None

    @classmethod
    def named(cls, names: list[str], **kwargs) -> Toolbox:
        unknown = [n for n in names if n not in SERVERS]
        if unknown:
            raise ValueError(f"unknown MCP server(s) {unknown}; known: {sorted(SERVERS)}")
        return cls([SERVERS[n] for n in names], **kwargs)

    def __enter__(self) -> Self:
        self._thread.start()
        try:
            self._run(self._connect_all())
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_exc) -> None:
        if self._stack is not None:
            # A server that won't shut down mustn't hide the error that got us here.
            with contextlib.suppress(Exception):
                self._run(self._stack.aclose(), timeout=30)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def _run(self, coro, timeout: float | None = None):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    async def _connect_all(self) -> None:
        self._stack = AsyncExitStack()
        blocked: list[str] = []
        try:
            await self._connect_each(blocked)
        except BaseException:
            if blocked:
                from clayzer.mcp_auth import NotSignedIn

                raise NotSignedIn(blocked[0]) from None
            raise

    async def _connect_each(self, blocked: list[str]) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        seen: dict[str, str] = {}
        for server in self.servers:
            if server.url:
                from mcp.client.streamable_http import streamable_http_client

                from clayzer.mcp_auth import (
                    NotSignedIn,
                    http_client,
                    oauth_provider,
                    stored_token_auth,
                )

                auth = None
                if server.oauth and self.interactive:
                    auth = oauth_provider(server.name, server.url, True, blocked)
                elif server.oauth:
                    # Batches and `clayzer tools`: the saved sign-in, refreshed as it expires.
                    auth = stored_token_auth(server.name, server.url)
                    if not auth.storage.signed_in():
                        raise NotSignedIn(
                            f"{server.name} needs a sign-in: run `clayzer login {server.name}` first"
                        )
                client = await self._stack.enter_async_context(http_client(auth))
                read, write = await self._stack.enter_async_context(
                    streamable_http_client(server.url, http_client=client)
                )
            else:
                command, args = server.launch()
                params = StdioServerParameters(command=command, args=args, env=dict(os.environ))
                read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            info = await session.initialize()
            self._sessions[server.name] = session
            impl = getattr(info, "server_info", None)
            self.versions[server.name] = (
                f"{impl.name} {impl.version}" if impl else server.package or server.url or ""
            )
            for tool in (await session.list_tools()).tools:
                if tool.name in seen:
                    raise ValueError(
                        f"tool {tool.name!r} is in both {seen[tool.name]!r} and {server.name!r}"
                    )
                if len(tool.name) > _NAME_LIMIT:
                    raise ValueError(f"tool name {tool.name!r} is longer than Bedrock allows")
                seen[tool.name] = server.name
                schema = tool.input_schema or {"type": "object", "properties": {}}
                self.specs.append(ToolSpec(tool.name, server.name, tool.description or "", schema))

    def server_for(self, name: str) -> str | None:
        return next((s.server for s in self.specs if s.name == name), None)

    def view(self, servers: list[str]) -> ToolView:
        """The tools of only some of the servers, sharing this Toolbox's connections: the
        model is offered its own tools, and the verifier's stay out of its prompt."""
        return ToolView(self, [s for s in self.specs if s.server in servers])

    def call(self, name: str, arguments: dict, timeout: float | None = None) -> ToolResult:
        """Call a tool. Failures come back as results, not exceptions: a failing tool is data
        for the evaluation, and the model sees the error and can recover. `timeout` overrides
        the Toolbox's for this call (building an LGND classifier takes minutes)."""
        server = self.server_for(name)
        if server is None:
            return ToolResult(f"unknown tool {name!r}", True, "UnknownTool")
        timeout = timeout or self.call_timeout
        try:
            result = self._run(self._sessions[server].call_tool(name, arguments), timeout)
        except TimeoutError:
            return ToolResult(f"{name} timed out after {timeout:.0f} s", True, "TimeoutError")
        except Exception as e:  # noqa: BLE001 - see docstring
            return ToolResult(f"{type(e).__name__}: {e}", True, type(e).__name__)
        parts = [
            getattr(b, "text", None) or b.model_dump_json() for b in getattr(result, "content", [])
        ]
        return ToolResult("\n".join(parts), bool(getattr(result, "is_error", False)))
