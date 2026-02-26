"""
PnL 计算器
注：核心逻辑已整合到 portfolio/manager.py（PortfolioManager）中。
本文件提供向后兼容的导入路径。
"""
from __future__ import annotations

# 重新导出，保持规划中的模块路径可用
from portfolio.manager import get_portfolio_manager as _get_pm


class PnLCalculator:
    """
    均价成本法盈亏计算工具。
    功能已整合到 PortfolioManager，此类为向后兼容保留。
    """

    @staticmethod
    def unrealized_pnl(avg_cost: float, current_price: float,
                        shares: float) -> tuple[float, float]:
        """
        计算未实现盈亏。
        Returns: (pnl_amount, pnl_pct)
        """
        pnl = (current_price - avg_cost) * shares
        pct = (current_price / avg_cost - 1) if avg_cost > 0 else 0.0
        return pnl, pct

    @staticmethod
    def realized_pnl(avg_cost: float, sell_price: float,
                      sell_shares: float, fee: float = 0.0) -> float:
        """计算已实现盈亏（含手续费）"""
        return (sell_price - avg_cost) * sell_shares - fee

    @staticmethod
    def new_avg_cost(old_shares: float, old_avg_cost: float,
                     new_shares: float, new_price: float,
                     fee: float = 0.0) -> float:
        """买入后计算新的均价成本（均价成本法）"""
        total_cost = old_shares * old_avg_cost + new_shares * new_price + fee
        total_shares = old_shares + new_shares
        return total_cost / total_shares if total_shares > 0 else new_price
