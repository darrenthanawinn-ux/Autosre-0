"""ToolHub: the single seam through which every agent touches the outside world.

McpHub spawns our MCP servers over stdio and routes tool calls by name, so agents are
pure reasoning code and every side effect is an auditable MCP tool call.
"""
import json
import sys
from contextlib import AsyncExitStack
from typing import Any, Protocol

SERVERS = {
    "gitlab": "autosre.mcp_servers.gitlab_mcp",
    "gcp": "autosre.mcp_servers.gcp_mcp",
}


class ToolHub(Protocol):
    async def call(self, tool: str, **args: Any) -> Any: ...


class McpHub:
    def __init__(self, servers: dict[str, str] | None = None):
        self.servers = servers or SERVERS
        self._stack = AsyncExitStack()
        self._route: dict[str, Any] = {}
        self.audit: list[dict] = []

    async def __aenter__(self) -> "McpHub":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        for module in self.servers.values():
            params = StdioServerParameters(command=sys.executable, args=["-m", module])
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                self._route[tool.name] = session
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    async def call(self, tool: str, **args: Any) -> Any:
        session = self._route[tool]
        res = await session.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in res.content)
        if res.isError:
            raise RuntimeError(f"MCP tool {tool} failed: {text}")
        self.audit.append({"tool": tool, "args": list(args)})
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
