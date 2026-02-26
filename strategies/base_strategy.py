"""
策略基类
所有策略继承此类，提供统一的模型训练/预测/选股接口
直接复用 Qlib 内置模型类，不从头重写
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger


@dataclass
class StrategyResult:
    """策略运行结果"""
    strategy_key:  str
    strategy_name: str
    scores:        pd.Series          # index=ticker, values=预测分数（降序排列）
    topk_tickers:  list[str]          # 最终选出的 Top-K 股票代码
    model_name:    str
    universe_size: int                # 参与筛选的股票数


class BaseStrategy(ABC):
    """量化策略基类"""

    KEY:  str = ""      # 策略标识符，子类必须定义
    NAME: str = ""      # 显示名称
    TOPK: int = 50      # 默认选出 Top-K

    def __init__(self, topk: Optional[int] = None):
        self.topk = topk or self.TOPK

    @abstractmethod
    def run(self,
            universe: list[str],
            progress_cb=None) -> StrategyResult:
        """
        执行选股流程
        universe:    候选股票代码列表
        progress_cb: 可选回调 (pct: int, msg: str) 用于进度上报
        """

    def _report(self, cb, pct: int, msg: str) -> None:
        if cb:
            try:
                cb(pct, msg)
            except Exception:
                pass
        logger.debug(f"[{self.KEY}] {pct}% - {msg}")
