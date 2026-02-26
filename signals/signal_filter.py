"""
信号过滤器
提供按类型、强度、持仓状态过滤 TradeSignal 列表的工具函数。
"""
from __future__ import annotations

from signals.signal_generator import TradeSignal


def filter_by_type(signals: list[TradeSignal],
                   signal_type: str) -> list[TradeSignal]:
    """按信号类型过滤，signal_type: 'BUY'/'SELL'/'HOLD'/'WATCH'"""
    if signal_type == "ALL" or not signal_type:
        return signals
    return [s for s in signals if s.signal == signal_type]


def filter_buy_signals(signals: list[TradeSignal]) -> list[TradeSignal]:
    return [s for s in signals if s.signal in ("BUY", "STRONG_BUY")]


def filter_sell_signals(signals: list[TradeSignal]) -> list[TradeSignal]:
    return [s for s in signals if s.signal == "SELL"]


def filter_portfolio_signals(signals: list[TradeSignal]) -> list[TradeSignal]:
    """只返回当前持仓中的股票信号"""
    return [s for s in signals if s.in_portfolio]
