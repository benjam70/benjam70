"""MCP stdio transport adapter for the repository's existing servers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .controller import SearchResultState, ToolResult
from .engine import SearchRequest


@dataclass(frozen=True)
class MCPServerSpec:
    source: str
    command: str
    args: tuple[str, ...]
    tool_name: str
    build_arguments: Callable[[SearchRequest], Mapping[str, Any]]
    normalize: Callable[[SearchRequest, Any], ToolResult]


class MCPStdioSearchExecutor:
    """Call existing MCP tools and require explicit result normalization.

    A new MCP process is started per search to keep lifecycle ownership simple.
    Callers can replace this with a persistent transport without changing the
    engine or controller contracts.
    """

    def __init__(self, specs: Mapping[str, MCPServerSpec]) -> None:
        self.specs = dict(specs)

    def search(self, request: SearchRequest) -> ToolResult:
        spec = self.specs.get(request.source)
        if spec is None:
            return ToolResult(request.source, SearchResultState.FAILED, False, error="no MCP server spec registered")
        try:
            return asyncio.run(self._call(spec, request))
        except Exception as exc:
            return ToolResult(request.source, SearchResultState.FAILED, False, error=f"{type(exc).__name__}: {exc}")

    async def _call(self, spec: MCPServerSpec, request: SearchRequest) -> ToolResult:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(command=spec.command, args=list(spec.args), env=None)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                raw = await session.call_tool(spec.tool_name, arguments=dict(spec.build_arguments(request)))
        return spec.normalize(request, raw)
