"""
交易信号生成器
将选股结果（预测分数）转化为 BUY/SELL/HOLD 信号
结合当前持仓判断是否需要操作
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger


@dataclass
class TradeSignal:
    """单条交易信号"""
    ticker:       str
    signal:       str           # "BUY" / "SELL" / "HOLD" / "WATCH"
    signal_zh:    str           # 中文
    score:        float         # Qlib 预测分数
    current_price:Optional[float]
    change_pct:   Optional[float]
    reason:       str           # 信号原因
    strength:     str           # "强" / "中" / "弱"
    generated_at: str           # ISO 时间字符串
    in_portfolio: bool = False  # 是否当前持仓


SIGNAL_MAP = {
    "BUY":        "买入",
    "STRONG_BUY": "强烈买入",
    "SELL":       "卖出",
    "HOLD":       "持有",
    "WATCH":      "观察",
}


class SignalGenerator:
    """
    从选股结果生成交易信号
    规则（基于分数百分位）：
      Top 10%  → BUY
      Top 10-30% → HOLD（如已持仓）/ WATCH（未持仓）
      Bottom 20% → SELL（如已持仓）/ 不出现（未持仓）
    """

    def generate(self, screening_results: list[dict]) -> list[TradeSignal]:
        """
        从选股结果列表生成信号
        screening_results: [{ticker, score, change_pct, ...}, ...]
        """
        if not screening_results:
            return []

        # 获取当前持仓集合
        portfolio_tickers = self._get_portfolio_tickers()

        # 分数百分位分布
        scores = [r.get("score", 0.0) for r in screening_results]
        total  = len(scores)
        now    = datetime.now().isoformat(timespec="seconds")

        signals: list[TradeSignal] = []

        for r in screening_results:
            ticker = r.get("ticker", "")
            score  = r.get("score", 0.0)
            in_portfolio = ticker in portfolio_tickers

            # 计算百分位（含等值排名，使用 rank+1 避免最高分无法到 top10%）
            rank = sum(1 for s in scores if s < score)
            percentile = (rank + 0.5) / total * 100

            # 信号判断
            if percentile >= 90:
                signal, reason, strength = "BUY", "Qlib 预测分数 Top 10%，强势买入信号", "强"
            elif percentile >= 70 and in_portfolio:
                signal, reason, strength = "HOLD", "分数中上，当前持仓维持", "中"
            elif percentile >= 70:
                signal, reason, strength = "WATCH", "分数中上，可关注", "中"
            elif percentile < 20 and in_portfolio:
                signal, reason, strength = "SELL", "Qlib 预测分数 Bottom 20%，建议减仓", "强"
            else:
                signal, reason, strength = "HOLD", "分数中性，观望", "弱"

            signals.append(TradeSignal(
                ticker=ticker,
                signal=signal,
                signal_zh=SIGNAL_MAP.get(signal, signal),
                score=score,
                current_price=None,   # 由外部更新
                change_pct=r.get("change_pct"),
                reason=reason,
                strength=strength,
                generated_at=now,
                in_portfolio=in_portfolio,
            ))

        # 排序：SELL > BUY > HOLD > WATCH
        order = {"SELL": 0, "BUY": 1, "STRONG_BUY": 1, "HOLD": 2, "WATCH": 3}
        signals.sort(key=lambda s: (order.get(s.signal, 9), -s.score))

        logger.info(
            f"信号生成完成：{len(signals)} 条，"
            f"BUY={sum(1 for s in signals if s.signal=='BUY')}，"
            f"SELL={sum(1 for s in signals if s.signal=='SELL')}"
        )
        return signals

    def _get_portfolio_tickers(self) -> set[str]:
        """获取当前持仓股票集合"""
        try:
            from portfolio.db import get_db
            positions = get_db().get_all_positions()
            return {p["symbol"] for p in positions}
        except Exception:
            return set()
