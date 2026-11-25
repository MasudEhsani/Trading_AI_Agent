# config.py - central paths and settings. Everything the agent writes goes under data/.
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repository folder

# Your own runs (paper.db, reports, logs). Ignored by git: it's your personal history.
DATA_DIR = Path(os.getenv("TRADING_DATA_DIR", ROOT / "data" / "live"))
DB_FILE = DATA_DIR / "paper.db"
REPORTS_DIR = DATA_DIR / "reports"

# Example output produced by scripts/generate_sample_data.py (committed to git).
SAMPLE_DIR = ROOT / "data" / "sample"

# The MCP server runs as its own process (python -m ...).
SERVER_MODULE = "trading_agent.server.trading_server"

# MCP passes only a few safe environment variables to a server process, so the
# settings the server needs are forwarded explicitly (see Agent(env=...)).
SERVER_ENV_VARS = ("MARKET_DATA", "TRADING_DATA_DIR")


def server_env() -> dict[str, str]:
    return {k: os.environ[k] for k in SERVER_ENV_VARS if k in os.environ}
