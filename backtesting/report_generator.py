"""
回测报告生成器
将 BacktestReport 格式化为可读文本或 CSV。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtesting.backtest_engine import BacktestReport


def to_text(report: "BacktestReport") -> str:
    """生成纯文本回测摘要"""
    if not report.available:
        return f"回测失败：{report.error}"

    m = report.metrics
    lines = [
        f"策略：{report.config.strategy_key}",
        f"区间：{report.config.start_date} ~ {report.config.end_date}",
        f"初始资金：${report.config.init_capital:,.0f}",
        "",
        f"年化收益：{m.annual_return*100:+.2f}%",
        f"总收益：  {m.total_return*100:+.2f}%",
        f"Sharpe：  {m.sharpe_ratio:.3f}",
        f"最大回撤：{m.max_drawdown*100:.2f}%",
        f"年化波动：{m.volatility*100:.2f}%",
        f"胜率：    {m.win_rate*100:.1f}%" if m.win_rate else "胜率：    --",
        f"IC 均值： {m.ic_mean:.4f}" if m.ic_mean else "IC 均值： --",
        f"ICIR：    {m.icir:.3f}" if m.icir else "ICIR：    --",
        f"Alpha：   {m.alpha*100:+.2f}%" if m.alpha else "Alpha：   --",
    ]
    return "\n".join(lines)


def to_csv(report: "BacktestReport", output_path: str | Path) -> bool:
    """将净值曲线导出为 CSV"""
    if not report.available or report.nav_series is None:
        return False
    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["日期索引", "策略净值", "基准净值"])
            bm = report.bm_series
            for i, nav in enumerate(report.nav_series):
                bm_val = bm.iloc[i] if bm is not None and i < len(bm) else ""
                writer.writerow([i, f"{nav:.6f}", f"{bm_val:.6f}" if bm_val != "" else ""])
        return True
    except Exception:
        return False
