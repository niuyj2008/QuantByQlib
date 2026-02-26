"""
持仓数据库（SQLite）
schema:
  positions        — 当前持仓（每支股票一行，多次买入自动加权平均成本）
  transactions     — 完整交易记录（买入/卖出/股息/拆股）
  corporate_actions— 企业行为（拆股/合股/股息），用于持仓成本校正
  goals            — 盈利目标
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger


# 默认数据库路径
DEFAULT_DB_PATH = Path.home() / ".quantbyqlib" / "portfolio.db"


class PortfolioDatabase:
    """SQLite 持仓数据库封装"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── 连接管理 ─────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """获取线程安全的数据库连接（每次新建，用完自动提交/关闭）"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row       # 支持列名访问
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # 写前日志，提高并发性
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema 初始化 ────────────────────────────────────────

    def _init_schema(self) -> None:
        """创建所有表（幂等，已存在则跳过）"""
        with self._conn() as conn:
            conn.executescript("""
                -- 当前持仓
                CREATE TABLE IF NOT EXISTS positions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT    NOT NULL UNIQUE,
                    shares      REAL    NOT NULL CHECK(shares > 0),
                    avg_cost    REAL    NOT NULL CHECK(avg_cost > 0),
                    first_buy_date TEXT NOT NULL,
                    sector      TEXT,
                    notes       TEXT,
                    updated_at  TEXT    NOT NULL
                );

                -- 交易记录
                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT    NOT NULL,
                    trans_type  TEXT    NOT NULL CHECK(trans_type IN ('BUY','SELL','DIVIDEND','SPLIT')),
                    shares      REAL    NOT NULL CHECK(shares > 0),
                    price       REAL    NOT NULL CHECK(price > 0),
                    amount      REAL    NOT NULL,
                    commission  REAL    NOT NULL DEFAULT 0,
                    trans_date  TEXT    NOT NULL,
                    notes       TEXT,
                    created_at  TEXT    NOT NULL
                );

                -- 企业行为（拆股/股息，用于成本校正）
                CREATE TABLE IF NOT EXISTS corporate_actions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT    NOT NULL,
                    action_type TEXT    NOT NULL CHECK(action_type IN ('SPLIT','REVERSE_SPLIT','DIVIDEND')),
                    ratio       REAL,
                    amount      REAL,
                    ex_date     TEXT    NOT NULL,
                    applied     INTEGER NOT NULL DEFAULT 0
                );

                -- 盈利目标
                CREATE TABLE IF NOT EXISTS goals (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT    NOT NULL,
                    period_type     TEXT    NOT NULL CHECK(period_type IN ('MONTHLY','QUARTERLY','YEARLY')),
                    target_return_pct REAL  NOT NULL,
                    start_date      TEXT    NOT NULL,
                    end_date        TEXT    NOT NULL,
                    initial_capital REAL    NOT NULL,
                    status          TEXT    NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','COMPLETED','CANCELLED')),
                    created_at      TEXT    NOT NULL
                );

                -- 索引
                CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON transactions(symbol);
                CREATE INDEX IF NOT EXISTS idx_transactions_date   ON transactions(trans_date);
                CREATE INDEX IF NOT EXISTS idx_goals_status        ON goals(status);
            """)
        logger.debug(f"数据库 schema 初始化完成：{self.db_path}")

    # ── 持仓操作 ─────────────────────────────────────────────

    def buy(self, symbol: str, shares: float, price: float,
            commission: float = 0.0, trans_date: Optional[str] = None,
            sector: Optional[str] = None, notes: Optional[str] = None) -> None:
        """
        记录买入：
        - 若已有持仓，加权平均成本后累加股数
        - 若无持仓，新建记录
        - 同时写入 transactions 表
        """
        symbol = symbol.upper().strip()
        now = datetime.now().isoformat()
        date = trans_date or datetime.now().strftime("%Y-%m-%d")

        with self._conn() as conn:
            # 计算总金额（含佣金计入成本）
            total_amount = shares * price + commission

            # 查询现有持仓
            row = conn.execute(
                "SELECT shares, avg_cost FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()

            if row:
                # 加权平均成本
                old_shares = row["shares"]
                old_cost   = row["avg_cost"]
                new_shares = old_shares + shares
                new_avg_cost = (old_shares * old_cost + total_amount) / new_shares
                conn.execute(
                    "UPDATE positions SET shares=?, avg_cost=?, updated_at=? WHERE symbol=?",
                    (new_shares, new_avg_cost, now, symbol)
                )
            else:
                # 新建持仓
                avg_cost = total_amount / shares
                conn.execute(
                    """INSERT INTO positions (symbol, shares, avg_cost, first_buy_date, sector, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, shares, avg_cost, date, sector, notes, now)
                )

            # 写交易记录
            conn.execute(
                """INSERT INTO transactions
                   (symbol, trans_type, shares, price, amount, commission, trans_date, notes, created_at)
                   VALUES (?, 'BUY', ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, shares, price, shares * price, commission, date, notes, now)
            )

        logger.info(f"买入记录：{symbol} {shares}股 @ ${price:.2f}（佣金 ${commission:.2f}）")

    def sell(self, symbol: str, shares: float, price: float,
             commission: float = 0.0, trans_date: Optional[str] = None,
             notes: Optional[str] = None) -> float:
        """
        记录卖出：
        - 检查持仓是否足够
        - 减少持仓，成本价不变
        - 全部卖出则删除持仓记录
        - 返回本次交易实现盈亏
        """
        from core.exceptions import InsufficientSharesError
        symbol = symbol.upper().strip()
        now = datetime.now().isoformat()
        date = trans_date or datetime.now().strftime("%Y-%m-%d")

        with self._conn() as conn:
            row = conn.execute(
                "SELECT shares, avg_cost FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()

            if not row:
                raise InsufficientSharesError(symbol, 0, shares)
            if row["shares"] < shares - 1e-6:
                raise InsufficientSharesError(symbol, row["shares"], shares)

            avg_cost = row["avg_cost"]
            realized_pnl = (price - avg_cost) * shares - commission
            remaining = row["shares"] - shares

            if remaining < 1e-6:
                # 全部卖出，删除持仓
                conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            else:
                conn.execute(
                    "UPDATE positions SET shares=?, updated_at=? WHERE symbol=?",
                    (remaining, now, symbol)
                )

            # 写交易记录
            conn.execute(
                """INSERT INTO transactions
                   (symbol, trans_type, shares, price, amount, commission, trans_date, notes, created_at)
                   VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, shares, price, shares * price, commission, date, notes, now)
            )

        logger.info(f"卖出记录：{symbol} {shares}股 @ ${price:.2f}，实现盈亏 ${realized_pnl:.2f}")
        return realized_pnl

    def get_all_positions(self) -> list[dict]:
        """获取所有持仓（不含当前价格，价格由 Worker 刷新填充）"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY symbol"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_position(self, symbol: str) -> Optional[dict]:
        """获取单只股票持仓"""
        symbol = symbol.upper().strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()
            return dict(row) if row else None

    def update_sector(self, symbol: str, sector: str) -> None:
        """更新持仓的行业分类（从 OpenBB 获取后回写）"""
        symbol = symbol.upper().strip()
        with self._conn() as conn:
            conn.execute(
                "UPDATE positions SET sector=?, updated_at=? WHERE symbol=?",
                (sector, datetime.now().isoformat(), symbol)
            )

    def delete_position(self, symbol: str) -> None:
        """删除持仓（不记录卖出，用于纠错）"""
        symbol = symbol.upper().strip()
        with self._conn() as conn:
            conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        logger.warning(f"已直接删除持仓记录：{symbol}（非卖出操作）")

    # ── 交易记录操作 ──────────────────────────────────────────

    def get_transactions(self, symbol: Optional[str] = None, limit: int = 200) -> list[dict]:
        """获取交易记录，可按 symbol 过滤"""
        with self._conn() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE symbol=? ORDER BY trans_date DESC LIMIT ?",
                    (symbol.upper(), limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM transactions ORDER BY trans_date DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_realized_pnl(self, symbol: Optional[str] = None) -> float:
        """
        计算已实现盈亏
        = 卖出总收入 - 卖出股份的买入成本 - 佣金
        （简化计算：用平均成本法）
        """
        with self._conn() as conn:
            if symbol:
                sells = conn.execute(
                    "SELECT * FROM transactions WHERE symbol=? AND trans_type='SELL'",
                    (symbol.upper(),)
                ).fetchall()
            else:
                sells = conn.execute(
                    "SELECT * FROM transactions WHERE trans_type='SELL'"
                ).fetchall()

            total_pnl = 0.0
            for sell in sells:
                sym = sell["symbol"]
                # 买入均价（从最近的持仓快照，简化：当时持仓 avg_cost 未保留，用 amount/shares 估算）
                # 精确计算需要快照历史，此处用保守估算
                sell_revenue = sell["amount"] - sell["commission"]
                # 获取该 symbol 的买入总成本（按时间排序，FIFO 近似）
                buys = conn.execute(
                    """SELECT SUM(amount) as total_buy, SUM(shares) as total_shares
                       FROM transactions WHERE symbol=? AND trans_type='BUY'
                       AND trans_date <= ?""",
                    (sym, sell["trans_date"])
                ).fetchone()
                if buys and buys["total_shares"] and buys["total_shares"] > 0:
                    avg_buy = buys["total_buy"] / buys["total_shares"]
                    pnl = (sell["price"] - avg_buy) * sell["shares"] - sell["commission"]
                    total_pnl += pnl

            return total_pnl

    # ── 盈利目标操作 ──────────────────────────────────────────

    def create_goal(self, name: str, period_type: str, target_return_pct: float,
                    start_date: str, end_date: str, initial_capital: float) -> int:
        """创建盈利目标，返回新目标 ID"""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO goals
                   (name, period_type, target_return_pct, start_date, end_date, initial_capital, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)""",
                (name, period_type, target_return_pct, start_date, end_date, initial_capital, now)
            )
            return cur.lastrowid

    def get_active_goals(self) -> list[dict]:
        """获取所有激活中的盈利目标"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE status='ACTIVE' ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_goals(self) -> list[dict]:
        """获取所有目标（含已完成/取消）"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_goal_status(self, goal_id: int, status: str) -> None:
        """更新目标状态（ACTIVE/COMPLETED/CANCELLED）"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET status=? WHERE id=?", (status, goal_id)
            )

    # ── 统计汇总 ──────────────────────────────────────────────

    def get_portfolio_summary(self, current_prices: Optional[dict] = None) -> dict:
        """
        计算持仓汇总指标
        current_prices: {symbol: current_price}，不传则只计算成本数据
        """
        positions = self.get_all_positions()
        if not positions:
            return {
                "total_invested": 0.0,
                "total_market_value": 0.0,
                "total_unrealized_pnl": 0.0,
                "total_unrealized_pct": 0.0,
                "total_realized_pnl": self.get_realized_pnl(),
                "position_count": 0,
            }

        total_invested = sum(p["shares"] * p["avg_cost"] for p in positions)
        total_market_value = 0.0
        prices = current_prices or {}

        for p in positions:
            price = prices.get(p["symbol"])
            if price is not None:
                total_market_value += p["shares"] * price
            else:
                total_market_value += p["shares"] * p["avg_cost"]  # 无价格时用成本价

        unrealized_pnl = total_market_value - total_invested
        unrealized_pct = (unrealized_pnl / total_invested) if total_invested > 0 else 0.0

        return {
            "total_invested":       total_invested,
            "total_market_value":   total_market_value,
            "total_unrealized_pnl": unrealized_pnl,
            "total_unrealized_pct": unrealized_pct,
            "total_realized_pnl":   self.get_realized_pnl(),
            "position_count":       len(positions),
        }


# ── 模块级单例 ────────────────────────────────────────────────

_db: Optional[PortfolioDatabase] = None


def get_db() -> PortfolioDatabase:
    """获取数据库单例"""
    global _db
    if _db is None:
        _db = PortfolioDatabase()
    return _db
