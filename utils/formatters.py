"""QuantByQlib 数字和文本格式化工具"""
from __future__ import annotations
from typing import Optional


def fmt_price(value: Optional[float], prefix: str = "$") -> str:
    """格式化价格，如 $1,234.56，值为 None 时显示 --"""
    if value is None:
        return "--"
    return f"{prefix}{value:,.2f}"


def fmt_pct(value: Optional[float], decimals: int = 2) -> str:
    """格式化百分比，如 +12.34%，值为 None 时显示 --"""
    if value is None:
        return "--"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{decimals}f}%"


def fmt_large_number(value: Optional[float]) -> str:
    """
    格式化大数字（市值等），如 2.14T / 567.8B / 12.3M
    值为 None 时显示 --
    """
    if value is None:
        return "--"
    abs_val = abs(value)
    if abs_val >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs_val >= 1e3:
        return f"{value / 1e3:.2f}K"
    return f"{value:.2f}"


def fmt_shares(value: Optional[float]) -> str:
    """格式化股数，如 1,234.00"""
    if value is None:
        return "--"
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def fmt_score(value: Optional[float]) -> str:
    """格式化 Qlib 模型评分（0-1），如 0.923"""
    if value is None:
        return "--"
    return f"{value:.3f}"


def fmt_ratio(value: Optional[float], decimals: int = 2) -> str:
    """格式化比率（PE/PB 等），如 62.3"""
    if value is None:
        return "--"
    return f"{value:.{decimals}f}"


def signal_text(signal: Optional[str]) -> str:
    """将英文信号名转换为中文显示"""
    mapping = {
        "BUY": "买入",
        "STRONG_BUY": "强烈买入",
        "SELL": "卖出",
        "STRONG_SELL": "强烈卖出",
        "HOLD": "持有",
        "WATCH": "观察",
    }
    if signal is None:
        return "--"
    return mapping.get(signal.upper(), signal)


def sentiment_text(score: Optional[float]) -> str:
    """将情绪得分（-1 到 1）转为中文描述"""
    if score is None:
        return "--"
    if score > 0.3:
        return "非常正面"
    if score > 0.05:
        return "偏正面"
    if score >= -0.05:
        return "中性"
    if score >= -0.3:
        return "偏负面"
    return "非常负面"
