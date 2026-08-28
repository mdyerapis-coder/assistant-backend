#!/usr/bin/env python3
"""Demo MCP server using stdio transport, exposing echo and add tools."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("demo")


@server.tool()
def echo(text: str) -> str:
    """Echo back the provided text."""
    return text


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


if __name__ == "__main__":
    server.run("stdio")
