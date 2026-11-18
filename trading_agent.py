# trading_agent.py - Milestone 6+7: chat with your research agent, approve orders, daily mode.
#   python trading_agent.py           interactive
#   python trading_agent.py --daily   unattended daily run -> reports/YYYY-MM-DD.md
import asyncio
import sys
from datetime import date
from pathlib import Path

from agent_core import Agent
from trading_server import HOST_ONLY_TOOLS

HERE = Path(__file__).parent
SYSTEM = f"""You are a careful research assistant for a PAPER trading account (simulated money,
for learning). Today is {date.today().isoformat()}.
- Get every number from the tools. Never invent prices or indicators.
- Always state which data source the tools report (simulated or real).
- You may PROPOSE orders with propose_order; you cannot execute them. A human decides.
- Every proposal needs a thesis: the reason (cite indicators) AND the main risk.
- Indicators describe the past; they do not predict the future. Say so when relevant,
  never promise profits, and don't present anything as financial advice.
- If the risk rules reject an order, explain why; don't try to work around the rules.
- Be concise. Reply in the user's language."""

DAILY_TASK = """Daily review. 1) market_overview, 2) get_portfolio, 3) analyze the 1-2 most
interesting symbols, 4) propose at most 2 orders if (and only if) you see a clear reason,
5) finish with a short report in Markdown: market summary, portfolio status, proposals
with thesis, and what to watch tomorrow."""

HELP = "Commands: /orders  /approve <id>  /reject <id>  /portfolio  /tokens  quit"


async def host_command(agent: Agent, line: str) -> str:
    """Commands typed by the HUMAN. These call the server directly, not through Claude."""
    cmd, *rest = line.split()
    calls = {"/orders": ("list_orders", {"status": "proposed"}),
             "/portfolio": ("get_portfolio", {})}
    if cmd in ("/approve", "/reject") and rest and rest[0].isdigit():
        tool = "execute_order" if cmd == "/approve" else "reject_order"
        calls[cmd] = (tool, {"order_id": int(rest[0])})
    if cmd == "/tokens":
        return str(agent.tokens)
    if cmd not in calls:
        return HELP
    tool, args = calls[cmd]
    result = await agent.mcp.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    if cmd in ("/approve", "/reject") and not result.is_error:
        # tell Claude what the human decided, so the conversation stays truthful
        note = f"(Note: I ran {cmd} {rest[0]}: {text})"
        agent.messages.append({"role": "user", "content": note})
        agent.messages.append({"role": "assistant", "content": "Noted."})
    return text


async def interactive():
    async with Agent(HERE / "trading_server.py", SYSTEM, hidden_tools=HOST_ONLY_TOOLS) as agent:
        print(f"Paper-trading research agent. Claude's tools: "
              f"{', '.join(t['name'] for t in agent.tools)}\n{HELP}\n")
        while True:
            line = input("You: ").strip()
            if line.lower() in ("quit", "exit", "q"):
                break
            if line.startswith("/"):
                print(await host_command(agent, line), "\n")
            elif line:
                print(f"Claude: {await agent.ask(line)}\n")


async def daily():
    """No human is watching: Claude may only propose. Orders wait for /approve later."""
    async with Agent(HERE / "trading_server.py", SYSTEM, hidden_tools=HOST_ONLY_TOOLS,
                     verbose=False) as agent:
        report = await agent.ask(DAILY_TASK)
        pending = (await agent.mcp.call_tool("list_orders", {"status": "proposed"})).content
        out = HERE / "reports" / f"{date.today().isoformat()}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(f"{report}\n\n---\n**Pending proposals** (approve with /approve <id>):\n"
                       f"```\n{pending[0].text}\n```\n_Tokens used: {agent.tokens}_\n",
                       encoding="utf-8")
        print(f"Report written: {out}")


if __name__ == "__main__":
    asyncio.run(daily() if "--daily" in sys.argv else interactive())
