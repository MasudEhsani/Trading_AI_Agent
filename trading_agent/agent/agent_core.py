# agent_core.py - a reusable MCP agent host: the Claude tool-use loop over one MCP server.
import sys
from pathlib import Path

from anthropic import Anthropic
from mcp import Client, StdioServerParameters

DEFAULT_MODEL = "claude-sonnet-5-5"


class Agent:
    """Connects to ONE MCP server and runs the agent loop for each question.

    usage:
        async with Agent("my_server.py", system="...") as agent:            # a script
        async with Agent("pkg.my_server", system="...", cwd=ROOT) as agent:  # a module
            answer = await agent.ask("question")
    """

    def __init__(self, server: str | Path, system: str, model: str = DEFAULT_MODEL,
                 needs_confirmation: set[str] = frozenset(), max_steps: int = 10,
                 confirm=None, verbose: bool = True, hidden_tools: set[str] = frozenset(),
                 cwd: str | Path | None = None, env: dict[str, str] | None = None):
        # "x.py" runs as a script, "pkg.module" runs as `python -m pkg.module`
        server = str(server)
        self.server_args = [server] if server.endswith(".py") else ["-m", server]
        self.cwd = cwd
        # MCP gives the server process only a few safe variables (PATH, HOME, ...).
        # Anything else it needs (e.g. MARKET_DATA) must be passed explicitly.
        self.env = env or {}
        self.system, self.model, self.max_steps = system, model, max_steps
        self.needs_confirmation = set(needs_confirmation)
        self.confirm = confirm or self._ask_in_terminal  # swap this for a GUI/Telegram later
        self.verbose = verbose
        self.hidden_tools = set(hidden_tools)    # tools Claude must never see or call
        self.claude = Anthropic()
        self.messages: list[dict] = []          # conversation memory
        self.tokens = {"input": 0, "output": 0}  # running total, to watch your costs

    # ----- connect / disconnect (async with) -----
    async def __aenter__(self):
        params = StdioServerParameters(command=sys.executable, args=self.server_args,
                                       cwd=self.cwd, env=self.env)
        self.mcp = Client(params)
        await self.mcp.__aenter__()
        listed = await self.mcp.list_tools()
        self.tools = [{"name": t.name, "description": t.description or "",
                       "input_schema": t.input_schema} for t in listed.tools
                      if t.name not in self.hidden_tools]
        # Prompt caching: tools + system prompt are identical on every call, so let the
        # API cache them (cheaper and faster once the prefix is long enough to be cached).
        self.tools[-1]["cache_control"] = {"type": "ephemeral"}
        return self

    async def __aexit__(self, *exc):
        await self.mcp.__aexit__(*exc)

    # ----- helpers -----
    @staticmethod
    def _ask_in_terminal(name: str, args: dict) -> bool:
        answer = input(f"  ⚠  Allow {name}({args})? [y/N] ")
        return answer.strip().lower() in ("y", "yes", "j", "ja")

    def log(self, text: str):
        if self.verbose:
            print(text)

    async def run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name in self.hidden_tools:  # second lock: even if Claude guesses the name
            return f"Tool {name} is not available to you.", True
        if name in self.needs_confirmation and not self.confirm(name, args):
            return "The user declined this action. Do not retry it.", True
        result = await self.mcp.call_tool(name, args)
        text = "\n".join(c.text for c in result.content if c.type == "text")
        return text, bool(result.is_error)

    # ----- the agent loop -----
    async def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        for step in range(1, self.max_steps + 1):
            response = self.claude.messages.create(
                model=self.model, max_tokens=2000, tools=self.tools, messages=self.messages,
                system=[{"type": "text", "text": self.system,
                         "cache_control": {"type": "ephemeral"}}])
            self.tokens["input"] += response.usage.input_tokens
            self.tokens["output"] += response.usage.output_tokens
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if b.type == "text")
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    text, is_error = await self.run_tool(block.name, block.input)
                    first = text.splitlines()[0] if text else ""
                    flag = "ERROR " if is_error else ""
                    self.log(f"  · {block.name}({block.input}) -> {flag}{first}")
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": text, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})
        return "(stopped: too many steps - try a more specific question)"
