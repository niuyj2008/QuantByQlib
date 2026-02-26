"""
持仓管理器
在 db.py（纯数据库操作）之上提供业务逻辑：
- 买入/卖出（含实时价格查询）
- 批量价格刷新
- 风险分析（集中度/持仓比例）
- 行业分布
"""
from __future__ import annotations

from typing import Optional
from loguru import logger

from portfolio.db import get_db, PortfolioDatabase
from core.exceptions import InsufficientSharesError, PortfolioError


class PortfolioManager:
    """持仓管理器（单例）"""

    def __init__(self, db: Optional[PortfolioDatabase] = None):
        self._db = db or get_db()

    # ── 交易操作 ──────────────────────────────────────────────

    def buy(self, symbol: str, shares: float, price: float,
            commission: float = 0.0, trans_date: Optional[str] = None,
            sector: Optional[str] = None, notes: Optional[str] = None) -> None:
        """买入股票，自动从 OpenBB 补全行业信息（如未提供）"""
        # 若未提供行业，尝试从 OpenBB 获取
        resolved_sector = sector
        if not resolved_sector:
            resolved_sector = self._fetch_sector(symbol)

        self._db.buy(
            symbol=symbol,
            shares=shares,
            price=price,
            commission=commission,
            trans_date=trans_date,
            sector=resolved_sector,
            notes=notes,
        )

        # 通知 UI 更新
        self._emit_portfolio_updated()

    def sell(self, symbol: str, shares: float, price: float,
             commission: float = 0.0, trans_date: Optional[str] = None,
             notes: Optional[str] = None) -> float:
        """
        卖出股票
        返回本次实现盈亏（正值盈利，负值亏损）
        """
        try:
            pnl = self._db.sell(
                symbol=symbol,
                shares=shares,
                price=price,
                commission=commission,
                trans_date=trans_date,
                notes=notes,
            )
            self._emit_portfolio_updated()
            return pnl
        except InsufficientSharesError:
            raise
        except Exception as e:
            raise PortfolioError(f"卖出 {symbol} 失败：{e}") from e

    def delete_position(self, symbol: str) -> None:
        """直接删除持仓（纠错用，不记录为卖出）"""
        self._db.delete_position(symbol)
        self._emit_portfolio_updated()

    # ── 数据查询 ──────────────────────────────────────────────

    def get_positions_with_prices(self) -> list[dict]:
        """
        获取持仓列表，并附上当前价格/盈亏数据
        每条记录包含：symbol/shares/avg_cost/sector/
                     current_price/market_value/unrealized_pnl/unrealized_pct/today_change_pct
        """
        positions = self._db.get_all_positions()
        if not positions:
            return []

        # 批量获取当前报价
        tickers = [p["symbol"] for p in positions]
        quotes = self._batch_get_quotes(tickers)

        enriched = []
        for pos in positions:
            sym = pos["symbol"]
            quote = quotes.get(sym) or {}
            current_price = quote.get("price") or pos["avg_cost"]
            shares = pos["shares"]
            avg_cost = pos["avg_cost"]

            market_value   = shares * current_price
            cost_basis     = shares * avg_cost
            unreal_pnl     = market_value - cost_basis
            unreal_pct     = unreal_pnl / cost_basis if cost_basis > 0 else 0.0
            today_change   = quote.get("change_pct")  # None 表示获取失败

            enriched.append({
                **pos,
                "current_price":   current_price,
                "market_value":    market_value,
                "cost_basis":      cost_basis,
                "unrealized_pnl":  unreal_pnl,
                "unrealized_pct":  unreal_pct,
                "today_change_pct":today_change,
                "price_available": quote.get("price") is not None,
            })

        # 按市值降序排列
        enriched.sort(key=lambda x: x["market_value"], reverse=True)
        return enriched

    def get_summary(self) -> dict:
        """获取持仓总览指标"""
        positions = self.get_positions_with_prices()
        if not positions:
            return {
                "total_invested": 0.0, "total_market_value": 0.0,
                "total_unrealized_pnl": 0.0, "total_unrealized_pct": 0.0,
                "total_realized_pnl": 0.0, "position_count": 0,
                "today_pnl": 0.0,
            }

        total_invested = sum(p["cost_basis"] for p in positions)
        total_market   = sum(p["market_value"] for p in positions)
        unreal_pnl     = total_market - total_invested
        unreal_pct     = unreal_pnl / total_invested if total_invested > 0 else 0.0
        realized_pnl   = self._db.get_realized_pnl()

        # 今日盈亏（有价格数据才计算）
        today_pnl = 0.0
        for p in positions:
            if p.get("today_change_pct") is not None and p["market_value"] > 0:
                # 今日盈亏 ≈ 昨收市值 * 今日涨跌幅
                yesterday_value = p["market_value"] / (1 + p["today_change_pct"] / 100)
                today_pnl += p["market_value"] - yesterday_value

        return {
            "total_invested":       total_invested,
            "total_market_value":   total_market,
            "total_unrealized_pnl": unreal_pnl,
            "total_unrealized_pct": unreal_pct,
            "total_realized_pnl":   realized_pnl,
            "position_count":       len(positions),
            "today_pnl":            today_pnl,
        }

    # ── 风险分析 ──────────────────────────────────────────────

    def get_risk_analysis(self) -> dict:
        """
        计算组合风险指标：
        - 单股集中度
        - 行业集中度
        - 最大持仓占比
        - 建议最大单笔买入（1% 风险法则）
        """
        positions = self.get_positions_with_prices()
        if not positions:
            return {"error": "暂无持仓数据"}

        total_value = sum(p["market_value"] for p in positions)
        if total_value <= 0:
            return {"error": "持仓市值为零"}

        # 单股集中度
        stock_weights = {
            p["symbol"]: p["market_value"] / total_value
            for p in positions
        }
        max_stock = max(stock_weights, key=stock_weights.get)
        max_weight = stock_weights[max_stock]

        # 行业集中度
        sector_values: dict[str, float] = {}
        for p in positions:
            sec = p.get("sector") or "未知行业"
            sector_values[sec] = sector_values.get(sec, 0.0) + p["market_value"]
        sector_weights = {k: v / total_value for k, v in sector_values.items()}
        max_sector = max(sector_weights, key=sector_weights.get)

        # 1% 风险法则：单笔最大买入金额 = 总资产 * 1% / 止损比例(8%)
        max_single_buy = total_value * 0.01 / 0.08

        return {
            "total_value":        total_value,
            "position_count":     len(positions),
            "stock_weights":      stock_weights,
            "max_stock":          max_stock,
            "max_stock_weight":   max_weight,
            "sector_weights":     sector_weights,
            "max_sector":         max_sector,
            "max_sector_weight":  sector_weights[max_sector],
            "max_single_buy":     max_single_buy,
            "concentration_risk": max_weight > 0.20,  # 单股超20%告警
            "sector_risk":        sector_weights[max_sector] > 0.40,
        }

    # ── 私有方法 ──────────────────────────────────────────────

    def _fetch_sector(self, symbol: str) -> Optional[str]:
        """从 OpenBB/FMP 获取行业分类"""
        try:
            from data.openbb_client import get_company_profile
            profile = get_company_profile(symbol)
            if profile:
                return profile.get("sector")
        except Exception as e:
            logger.debug(f"获取 {symbol} 行业失败：{e}")
        return None

    def _batch_get_quotes(self, tickers: list[str]) -> dict[str, Optional[dict]]:
        """批量获取报价，失败的返回 None"""
        try:
            from data.openbb_client import get_batch_quotes
            return get_batch_quotes(tickers)
        except Exception as e:
            logger.warning(f"批量报价失败：{e}")
            return {t: None for t in tickers}

    def _emit_portfolio_updated(self) -> None:
        """发射持仓更新事件"""
        try:
            from core.event_bus import get_event_bus
            get_event_bus().portfolio_updated.emit()
        except Exception:
            pass


# ── 模块级单例 ────────────────────────────────────────────────

_manager: Optional[PortfolioManager] = None


def get_portfolio_manager() -> PortfolioManager:
    """获取持仓管理器单例"""
    global _manager
    if _manager is None:
        _manager = PortfolioManager()
    return _manager
