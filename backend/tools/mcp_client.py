"""
MCP client layer - connects the (synchronous) research agent to MCP servers.

How it works
  * One background thread runs an asyncio loop.
  * Each MCP server (a subprocess speaking MCP over stdio) lives in its own long-lived
    task on that loop, so the stdio contexts are opened and closed in the same task.
  * Agent code just calls  mcp.call("server", ["tool_name"], {...})  - a normal blocking call
    with a timeout and one retry for transient failures.

Servers (all free / open source):
  tavily      npx tavily-mcp           web search      needs TAVILY_API_KEY + Node.js
  fetch       python -m mcp_server_fetch  page -> markdown   pip package
  filesystem  npx server-filesystem    research/ folder only   needs Node.js
  academic    mcp_servers/academic_server.py  arXiv/OpenAlex/Crossref/Semantic Scholar
  playwright  npx @playwright/mcp      JS-rendered pages (opt-in: ENABLE_PLAYWRIGHT_MCP=true)

A server that is not configured or fails to start is simply marked unavailable;
the agent keeps working without it.
"""

import asyncio
import concurrent.futures
import importlib.util
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


def research_dir() -> Path:
    """The ONLY folder the Filesystem MCP server may touch."""
    return Path(os.getenv("RESEARCH_DIR") or PROJECT_DIR / "research").resolve()


class MCPError(Exception):
    """Base class for MCP failures."""


class MCPUnavailable(MCPError):
    """Server is not configured / not running."""


class MCPToolError(MCPError):
    """The tool ran but reported an error (or timed out)."""


@dataclass
class ToolResult:
    text: str
    structured: dict | None = None


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    startup_timeout: float = 90.0   # first npx run downloads the package, so be generous
    serial: bool = False            # True = never run two calls at once (browser)


def _norm(name: str) -> str:
    return name.lower().replace("-", "_")


class _Server:
    """One connected MCP server (runs inside the manager's event loop)."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self.session = None
        self.tools: dict[str, str] = {}      # normalized name -> real name
        self.state = "starting"              # starting | ready | failed | stopped
        self.detail = ""
        self.ready = threading.Event()       # set when startup finished (ok or not)
        self.stop_evt: asyncio.Event | None = None
        self.lock = threading.Lock() if cfg.serial else None
        self.deadline = time.time() + cfg.startup_timeout + 10

    async def run(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self.stop_evt = asyncio.Event()
        params = StdioServerParameters(command=self.cfg.command, args=self.cfg.args,
                                       env=self.cfg.env or None)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), self.cfg.startup_timeout)
                    listed = await asyncio.wait_for(session.list_tools(), 30)
                    self.tools = {_norm(t.name): t.name for t in listed.tools}
                    self.session = session
                    self.state = "ready"
                    self.ready.set()
                    await self.stop_evt.wait()
        except BaseException as exc:  # noqa: BLE001 - report any startup / runtime failure
            if self.state != "ready":
                self.state = "failed"
                self.detail = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            self.session = None
            if self.state == "ready":
                self.state = "stopped"
            self.ready.set()

    def resolve(self, candidates: list[str]) -> str | None:
        for c in candidates:
            if _norm(c) in self.tools:
                return self.tools[_norm(c)]
        return None


class MCPManager:
    def __init__(self):
        self.servers: dict[str, _Server] = {}
        self.disabled: dict[str, str] = {}   # name -> reason it was not started
        self.loop: asyncio.AbstractEventLoop | None = None
        self._futures: list[concurrent.futures.Future] = []
        self.started = False

    # ---------------------------------------------------------- configuration
    def build_configs(self) -> list[ServerConfig]:
        configs: list[ServerConfig] = []
        npx = shutil.which("npx")  # resolves npx.cmd on Windows
        rdir = research_dir()

        # 1) Tavily - web search (free tier)
        if not os.getenv("TAVILY_API_KEY"):
            self.disabled["tavily"] = "TAVILY_API_KEY not set (DuckDuckGo is used instead)"
        elif not npx:
            self.disabled["tavily"] = "Node.js / npx not found"
        else:
            configs.append(ServerConfig("tavily", npx, ["-y", "tavily-mcp@latest"],
                                        {"TAVILY_API_KEY": os.environ["TAVILY_API_KEY"]}))

        # 2) Fetch - webpage -> markdown (Python package)
        if importlib.util.find_spec("mcp_server_fetch") is None:
            self.disabled["fetch"] = "package mcp-server-fetch not installed (pip install mcp-server-fetch)"
        else:
            configs.append(ServerConfig("fetch", sys.executable, ["-m", "mcp_server_fetch"],
                                        startup_timeout=45))

        # 3) Filesystem - restricted to the research folder
        if not npx:
            self.disabled["filesystem"] = "Node.js / npx not found"
        else:
            rdir.mkdir(parents=True, exist_ok=True)
            configs.append(ServerConfig("filesystem", npx,
                                        ["-y", "@modelcontextprotocol/server-filesystem", str(rdir)]))

        # 4) Academic - our own lightweight FastMCP server
        env = {k: os.environ[k] for k in ("CONTACT_EMAIL", "SEMANTIC_SCHOLAR_API_KEY") if os.getenv(k)}
        configs.append(ServerConfig("academic", sys.executable,
                                    [str(BACKEND_DIR / "mcp_servers" / "academic_server.py")],
                                    env, startup_timeout=30))

        # 5) Playwright - JS-rendered pages (opt-in because it launches a browser)
        if os.getenv("ENABLE_PLAYWRIGHT_MCP", "").lower() not in ("1", "true", "yes"):
            self.disabled["playwright"] = "disabled (set ENABLE_PLAYWRIGHT_MCP=true to enable)"
        elif not npx:
            self.disabled["playwright"] = "Node.js / npx not found"
        else:
            browser = os.getenv("PLAYWRIGHT_MCP_BROWSER") or ("msedge" if sys.platform == "win32" else "chromium")
            configs.append(ServerConfig("playwright", npx,
                                        ["-y", "@playwright/mcp@latest", "--headless", "--browser", browser],
                                        serial=True, startup_timeout=120))
        return configs

    # -------------------------------------------------------------- lifecycle
    def start(self):
        """Start all configured servers in the background (does not block)."""
        if self.started:
            return
        self.started = True
        try:
            import mcp  # noqa: F401
        except ImportError:
            for name in ("tavily", "fetch", "filesystem", "academic", "playwright"):
                self.disabled[name] = "Python package 'mcp' not installed (pip install -r requirements.txt)"
            return

        self.loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="mcp-loop").start()
        for cfg in self.build_configs():
            srv = _Server(cfg)
            self.servers[cfg.name] = srv
            self._futures.append(asyncio.run_coroutine_threadsafe(srv.run(), self.loop))

    def stop(self):
        if not self.loop:
            return
        for srv in self.servers.values():
            if srv.stop_evt is not None:
                self.loop.call_soon_threadsafe(srv.stop_evt.set)
        for fut in self._futures:
            try:
                fut.result(timeout=8)
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.started = False

    # ----------------------------------------------------------------- status
    def is_ready(self, name: str, wait: bool = True) -> bool:
        """True if the server is connected. Waits for a still-starting server (up to its deadline)."""
        srv = self.servers.get(name)
        if srv is None:
            return False
        if wait and srv.state == "starting":
            srv.ready.wait(timeout=max(0.0, srv.deadline - time.time()))
        return srv.state == "ready"

    def status(self) -> dict[str, dict]:
        out = {n: {"state": "disabled", "detail": why} for n, why in self.disabled.items()}
        for n, s in self.servers.items():
            out[n] = {"state": s.state, "detail": s.detail or f"{len(s.tools)} tools"}
        return out

    # ------------------------------------------------------------------- call
    def call(self, server: str, tools: list[str], arguments: dict,
             timeout: float = 30.0, retries: int = 1) -> ToolResult:
        """Blocking tool call. `tools` = acceptable tool names (first one the server has is used)."""
        if not self.is_ready(server):
            srv = self.servers.get(server)
            why = (srv.detail or srv.state) if srv else self.disabled.get(server, "not configured")
            raise MCPUnavailable(f"{server}: {why}")
        srv = self.servers[server]
        real_name = srv.resolve(tools)
        if real_name is None:
            raise MCPUnavailable(f"{server}: none of {tools} exist (has: {sorted(srv.tools.values())})")

        async def _do():
            return await asyncio.wait_for(srv.session.call_tool(real_name, arguments), timeout)

        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                if srv.lock:
                    srv.lock.acquire()
                try:
                    result = asyncio.run_coroutine_threadsafe(_do(), self.loop).result(timeout + 5)
                finally:
                    if srv.lock:
                        srv.lock.release()
            except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                last = MCPToolError(f"{server}.{real_name} timed out after {timeout:.0f}s")
            except Exception as exc:  # transport problem
                last = MCPToolError(f"{server}.{real_name} failed: {type(exc).__name__}: {exc}")
            else:
                text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
                if getattr(result, "isError", False):
                    raise MCPToolError(text or f"{server}.{real_name} returned an error")  # no retry
                return ToolResult(text=text, structured=getattr(result, "structuredContent", None))
            if attempt < retries:
                time.sleep(1.0 + attempt)
        raise last  # type: ignore[misc]


# Process-wide singleton used by every tool module.
mcp_manager = MCPManager()
