"""
持仓风险分析器
分析集中度风险、Beta、仓位建议
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskReport:
    """持仓风险分析报告"""
    total_value:         float
    concentration_warnings: list[dict] = field(default_factory=list)
    # 格式：[{"symbol": "NVDA", "pct": 0.34, "msg": "仓位 34%，超过建议上限 10%"}]
    sector_warnings:     list[dict] = field(default_factory=list)
    portfolio_beta:      Optional[float] = None
    max_single_buy_usd:  Optional[float] = None   # 1% 风险法则建议单笔金额
    risk_level:          str = "未知"               # 低 / 中 / 高


class RiskAnalyzer:
    """
    持仓风险分析。
    依赖 portfolio.manager.PortfolioManager 获取持仓数据。
    """

    # 集中度阈值
    SINGLE_STOCK_WARN_PCT  = 0.10   # 单股 > 10% 预警
    SECTOR_WARN_PCT        = 0.50   # 单行业 > 50% 预警

    def analyze(self, positions: list[dict],
                total_value: float,
                stop_loss_pct: float = 0.08) -> RiskReport:
        """
        positions: PortfolioManager.get_positions() 返回的持仓列表
        total_value: 总持仓市值
        stop_loss_pct: 止损比例，用于 1% 风险法则
        """
        report = RiskReport(total_value=total_value)

        if total_value <= 0 or not positions:
            return report

        # 集中度分析
        for pos in positions:
            shares = pos.get("shares", 0)
            price  = pos.get("current_price") or pos.get("avg_cost", 0)
            mv     = shares * price
            pct    = mv / total_value
            if pct > self.SINGLE_STOCK_WARN_PCT:
                report.concentration_warnings.append({
                    "symbol": pos.get("symbol", ""),
                    "pct":    pct,
                    "msg":    f"仓位 {pct*100:.1f}%，超过建议上限 {self.SINGLE_STOCK_WARN_PCT*100:.0f}%",
                })

        # 风险等级（简化）
        if report.concentration_warnings:
            report.risk_level = "高"
        elif total_value > 0:
            report.risk_level = "中"

        # 1% 风险法则：单笔买入金额 = 总资产 × 1% ÷ 止损比例
        if stop_loss_pct > 0:
            report.max_single_buy_usd = total_value * 0.01 / stop_loss_pct

        return report
