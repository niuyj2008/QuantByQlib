"""
Alpha158 因子读取器
从已初始化的 Qlib 数据中读取最新技术因子值
未初始化时返回空字典（不抛异常）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class TechnicalSignal:
    """Alpha158 技术信号数据结构"""
    ticker:          str
    factor_values:   dict[str, float] = field(default_factory=dict)
    composite_score: Optional[float]  = None   # 0-1，None 表示无数据
    available:       bool             = False

    @property
    def signal(self) -> str:
        """根据综合分数返回信号文字"""
        if self.composite_score is None:
            return "暂无数据"
        if self.composite_score >= 0.65:
            return "bullish"
        if self.composite_score <= 0.35:
            return "bearish"
        return "neutral"


# 要展示的 Alpha158 因子子集（对散户最有参考价值的）
DISPLAY_FACTORS: dict[str, str] = {
    # 价格动量
    "RESI5":  "5日超额收益",
    "RESI10": "10日超额收益",
    "RESI20": "20日超额收益",
    # 均价偏离
    "MA5":    "5日均价比",
    "MA10":   "10日均价比",
    "MA20":   "20日均价比",
    "MA30":   "30日均价比",
    # 成交量动量
    "WVMA5":  "5日量价动量",
    "WVMA20": "20日量价动量",
    # 波动率
    "RVOL5":  "5日相对波动",
    "RVOL20": "20日相对波动",
    # Beta / 换手
    "BETA5":  "5日 Beta",
    "TURN5":  "5日换手率",
    "TURN20": "20日换手率",
    # MACD 类
    "MACD":   "MACD 值",
    "KDJ_K":  "KDJ-K 值",
    "KDJ_D":  "KDJ-D 值",
    # RSI
    "RSI":    "RSI(14)",
}

# 信号解读规则（因子名 → 解读函数）
def _interpret_factor(name: str, value: float) -> tuple[str, str]:
    """
    返回 (信号文字, 颜色键)
    颜色键: "bullish" | "bearish" | "neutral"
    """
    if name.startswith("RESI"):
        if value > 0.02:   return "超额上涨", "bullish"
        if value < -0.02:  return "超额下跌", "bearish"
        return "中性", "neutral"

    if name.startswith("MA"):
        if value > 1.02:   return "价格偏高", "bearish"
        if value < 0.98:   return "价格偏低", "bullish"
        return "均价附近", "neutral"

    if name == "RSI":
        if value > 70:     return "超买", "bearish"
        if value < 30:     return "超卖", "bullish"
        return "正常区间", "neutral"

    if name == "MACD":
        if value > 0:      return "多头", "bullish"
        if value < 0:      return "空头", "bearish"
        return "零轴附近", "neutral"

    if name.startswith("RVOL"):
        if value > 1.5:    return "高波动", "bearish"
        if value < 0.5:    return "低波动", "neutral"
        return "正常波动", "neutral"

    if name.startswith("WVMA"):
        if value > 0.01:   return "量价上升", "bullish"
        if value < -0.01:  return "量价下降", "bearish"
        return "量价平稳", "neutral"

    return "--", "neutral"


class Alpha158Reader:
    """从 Qlib 数据集读取 Alpha158 因子值"""

    def __init__(self):
        self._initialized = False
        self._check_init()

    def _check_init(self) -> None:
        """检查 Qlib 是否已初始化"""
        try:
            from core.app_state import get_state
            self._initialized = get_state().qlib_initialized
        except Exception:
            self._initialized = False

    def get_latest_factors(self, ticker: str) -> dict[str, float]:
        """
        获取 ticker 的最新 Alpha158 因子值
        返回 {factor_name: value}，失败返回空字典
        """
        if not self._initialized:
            self._check_init()
        if not self._initialized:
            logger.debug(f"Qlib 未初始化，跳过 Alpha158 因子获取：{ticker}")
            return {}

        try:
            from qlib.data import D
            import pandas as pd
            from datetime import date, timedelta

            fields = list(DISPLAY_FACTORS.keys())
            start_time = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
            end_time   = date.today().strftime("%Y-%m-%d")
            df = D.features(
                [ticker.upper()],
                fields,
                start_time=start_time,
                end_time=end_time,
                freq="day",
            )
            if df is None or df.empty:
                return {}

            # 取最新一行
            latest = df.iloc[-1]
            result = {}
            for f in fields:
                try:
                    val = latest.get(f)
                    if val is not None and not (hasattr(val, '__float__') and
                                                 __import__('math').isnan(float(val))):
                        result[f] = float(val)
                except Exception:
                    pass
            return result

        except Exception as e:
            logger.debug(f"Alpha158 因子获取失败 {ticker}：{e}")
            return {}

    def get_factor_signals(self, factor_values: dict) -> list[dict]:
        """
        接收 {factor_name: value} 字典，返回格式化信号列表
        每条：{name, label, value_str, signal_text, signal_type}
        """
        result = []
        for name, label in DISPLAY_FACTORS.items():
            value = factor_values.get(name)
            if value is not None:
                sig_text, sig_type = _interpret_factor(name, value)
                result.append({
                    "name":        name,
                    "label":       label,
                    "value_str":   f"{value:.4f}",
                    "signal_text": sig_text,
                    "signal_type": sig_type,   # bullish / bearish / neutral
                })
        return result

    def get_factor_signals_by_ticker(self, ticker: str) -> list[dict]:
        """通过 ticker 拉取因子值后转化为信号列表（向下兼容）"""
        factors = self.get_latest_factors(ticker)
        return self.get_factor_signals(factors)

    def get_composite_score(self, ticker: str) -> Optional[float]:
        """
        基于 Alpha158 因子计算综合技术评分（0-1）
        简单加权：看多因子 +1，看空因子 -1，归一化到 0-1
        """
        signals = self.get_factor_signals_by_ticker(ticker)
        if not signals:
            return None

        score = 0.0
        for s in signals:
            if s["signal_type"] == "bullish":
                score += 1
            elif s["signal_type"] == "bearish":
                score -= 1

        # 归一化到 0-1
        total = len(signals)
        normalized = (score + total) / (2 * total) if total > 0 else 0.5
        return round(normalized, 3)

    def get_technical_signal(self, ticker: str) -> Optional["TechnicalSignal"]:
        """
        返回 TechnicalSignal 数据对象（含 factor_values 和 composite_score）
        供 stock_analyzer.py 使用
        """
        factor_values = self.get_latest_factors(ticker)
        composite = None

        if factor_values:
            signals = self.get_factor_signals(factor_values)
            score = 0.0
            for s in signals:
                if s["signal_type"] == "bullish":
                    score += 1
                elif s["signal_type"] == "bearish":
                    score -= 1
            total = len(signals)
            composite = round((score + total) / (2 * total), 3) if total > 0 else 0.5

        return TechnicalSignal(
            ticker=ticker,
            factor_values=factor_values,
            composite_score=composite,
            available=bool(factor_values),
        )
