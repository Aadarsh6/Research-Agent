"""
Offline stand-in for the `mcp` SDK. It lets the tests run the REAL MCPManager / tool wrappers
without Node.js, network access or API keys: each "server" is a dict of Python handlers.
"""

import json
import sys
import types
from contextlib import asynccontextmanager

CALLS: list[tuple[str, str, dict]] = []   # (server, tool, arguments) - lets tests count real calls
HANDLERS: dict[str, dict] = {}            # server key -> {tool_name: callable(args)}
FAIL_START: set[str] = set()


class ToolErr(Exception):
    """A handler raises this to simulate a tool returning isError=true."""


def _server_key(params) -> str:
    joined = " ".join([params.command] + list(params.args))
    for key, marker in (("tavily", "tavily-mcp"), ("fetch", "mcp_server_fetch"),
                        ("filesystem", "server-filesystem"), ("academic", "academic_server"),
                        ("playwright", "@playwright/mcp")):
        if marker in joined:
            return key
    return "unknown"


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text, structured=None, is_error=False):
        self.content, self.structuredContent, self.isError = [_Block(text)], structured, is_error


class _Tool:
    def __init__(self, name):
        self.name = name


class ClientSession:
    def __init__(self, read, write):
        self.key = read

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        return None

    async def list_tools(self):
        return types.SimpleNamespace(tools=[_Tool(n) for n in HANDLERS[self.key]])

    async def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        CALLS.append((self.key, name, arguments))
        try:
            out = HANDLERS[self.key][name](arguments)
        except ToolErr as exc:
            return _Result(str(exc), is_error=True)
        if isinstance(out, dict):
            return _Result(json.dumps(out), structured=out)
        return _Result(out)


class StdioServerParameters:
    def __init__(self, command, args=None, env=None):
        self.command, self.args, self.env = command, args or [], env


@asynccontextmanager
async def stdio_client(params):
    key = _server_key(params)
    if key in FAIL_START or key not in HANDLERS:
        raise RuntimeError(f"cannot start {key}")
    yield key, None


class FastMCP:                      # decorator-only stub so academic_server.py can be imported
    def __init__(self, name):
        self.name = name

    def tool(self):
        return lambda fn: fn

    def run(self):
        pass


def install():
    """Replace the real SDK with this fake in sys.modules."""
    mods = {
        "mcp": types.ModuleType("mcp"),
        "mcp.client": types.ModuleType("mcp.client"),
        "mcp.client.stdio": types.ModuleType("mcp.client.stdio"),
        "mcp.server": types.ModuleType("mcp.server"),
        "mcp.server.fastmcp": types.ModuleType("mcp.server.fastmcp"),
    }
    mods["mcp"].ClientSession, mods["mcp"].StdioServerParameters = ClientSession, StdioServerParameters
    mods["mcp.client.stdio"].stdio_client = stdio_client
    mods["mcp.server.fastmcp"].FastMCP = FastMCP
    sys.modules.update(mods)
