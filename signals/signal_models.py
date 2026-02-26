"""
信号数据模型
注：TradeSignal dataclass 已定义在 signals/signal_generator.py。
本文件重新导出，保持规划中的模块路径可用。
"""
from __future__ import annotations

from signals.signal_generator import TradeSignal, SIGNAL_MAP

__all__ = ["TradeSignal", "SIGNAL_MAP"]
