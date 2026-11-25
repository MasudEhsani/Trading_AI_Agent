# broker.py - a paper (simulated) broker in SQLite. No real money, ever.
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from trading_agent.config import DB_FILE

START_CASH = 10_000.0
FEE_EUR = 1.0          # flat fee per trade, like a cheap broker
SLIPPAGE_PCT = 0.05    # you never get exactly the last price

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL);
CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, qty INTEGER NOT NULL,
                                      avg_price REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY, created TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, qty INTEGER NOT NULL,
    status TEXT NOT NULL,          -- proposed | filled | rejected
    thesis TEXT,                   -- WHY the agent wants this trade (journal!)
    fill_price REAL, decided TEXT
);
"""


class PaperBroker:
    """Every method opens its own short-lived connection. Important: the MCP server runs
    tools in worker threads, and a SQLite connection may only be used by its own thread."""

    def __init__(self, path: Path = DB_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO account VALUES (1, ?)", (START_CASH,))

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()      # all changes in one block are saved together ...
        except Exception:
            conn.rollback()    # ... or not at all
            raise
        finally:
            conn.close()

    # ----- reading -----
    def cash(self) -> float:
        with self._db() as db:
            return db.execute("SELECT cash FROM account").fetchone()["cash"]

    def positions(self) -> dict[str, dict]:
        with self._db() as db:
            return {r["symbol"]: dict(r) for r in db.execute("SELECT * FROM positions")}

    def orders(self, status: str | None = None, limit: int = 20) -> list[dict]:
        sql, args = "SELECT * FROM orders", []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._db() as db:
            return [dict(r) for r in db.execute(sql, args + [limit])]

    def orders_today(self, day: date | None = None) -> int:
        """Proposed + filled orders created on `day` (default today); rejected don't count."""
        day = day or date.today()
        with self._db() as db:
            return db.execute(
                "SELECT count(*) FROM orders WHERE created LIKE ? AND status != 'rejected'",
                (day.isoformat() + "%",)).fetchone()[0]

    def get(self, order_id: int) -> dict:
        with self._db() as db:
            row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            raise KeyError(f"No order with id {order_id}")
        return dict(row)

    # ----- writing -----
    # `at=` lets scripts replay the past (e.g. scripts/generate_sample_data.py).
    def propose(self, symbol: str, side: str, qty: int, thesis: str,
                at: datetime | None = None) -> int:
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO orders (created, symbol, side, qty, status, thesis) "
                "VALUES (?, ?, ?, ?, 'proposed', ?)",
                ((at or datetime.now()).isoformat(timespec="seconds"), symbol, side, qty,
                 thesis))
            return cur.lastrowid

    def reject(self, order_id: int, at: datetime | None = None) -> None:
        with self._db() as db:
            db.execute("UPDATE orders SET status = 'rejected', decided = ? WHERE id = ?",
                       ((at or datetime.now()).isoformat(timespec="seconds"), order_id))

    def fill(self, order_id: int, market_price: float, at: datetime | None = None) -> dict:
        """Execute a proposed order at market price + slippage + fee (all simulated).
        Cash, position and order status change in ONE transaction: all or nothing."""
        o = self.get(order_id)
        if o["status"] != "proposed":
            raise ValueError(f"order {order_id} is already {o['status']}")
        sign = 1 if o["side"] == "buy" else -1
        price = round(market_price * (1 + sign * SLIPPAGE_PCT / 100), 2)
        cash_change = -sign * o["qty"] * price - FEE_EUR
        with self._db() as db:
            cash = db.execute("SELECT cash FROM account").fetchone()["cash"]
            if cash + cash_change < 0:
                raise ValueError("not enough cash")
            row = db.execute("SELECT qty, avg_price FROM positions WHERE symbol = ?",
                             (o["symbol"],)).fetchone()
            old_qty, old_avg = (row["qty"], row["avg_price"]) if row else (0, 0.0)
            new_qty = old_qty + sign * o["qty"]
            if new_qty < 0:
                raise ValueError("cannot sell more than you hold")
            if new_qty == 0:
                db.execute("DELETE FROM positions WHERE symbol = ?", (o["symbol"],))
            else:
                avg = old_avg if sign < 0 else (old_qty * old_avg + o["qty"] * price) / new_qty
                db.execute("INSERT OR REPLACE INTO positions VALUES (?, ?, ?)",
                           (o["symbol"], new_qty, round(avg, 4)))
            db.execute("UPDATE account SET cash = round(cash + ?, 2)", (cash_change,))
            db.execute("UPDATE orders SET status = 'filled', fill_price = ?, decided = ? "
                       "WHERE id = ?",
                       (price, (at or datetime.now()).isoformat(timespec="seconds"),
                        order_id))
        return self.get(order_id)
