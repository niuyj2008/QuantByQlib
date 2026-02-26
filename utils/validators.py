"""QuantByQlib 输入校验工具"""
from __future__ import annotations
import re
from typing import Optional


def validate_ticker(ticker: str) -> tuple[bool, str]:
    """
    校验美股 ticker 格式
    返回 (是否合法, 错误信息)
    """
    if not ticker:
        return False, "股票代码不能为空"
    ticker = ticker.strip().upper()
    # 美股 ticker：1-5 个大写字母，可含 "." 和 "-"（如 BRK.B、ADR-A）
    if not re.match(r'^[A-Z]{1,5}([.\-][A-Z]{1,2})?$', ticker):
        return False, f"无效的股票代码格式：{ticker}（示例：AAPL、NVDA、BRK.B）"
    return True, ""


def validate_price(value: str) -> tuple[bool, Optional[float], str]:
    """
    校验价格输入（正数）
    返回 (是否合法, 浮点值, 错误信息)
    """
    try:
        v = float(value.replace(",", ""))
        if v <= 0:
            return False, None, "价格必须大于 0"
        return True, v, ""
    except (ValueError, AttributeError):
        return False, None, f"无效价格：{value}"


def validate_shares(value: str) -> tuple[bool, Optional[float], str]:
    """
    校验股数输入（正数，允许小数 ETF 等）
    返回 (是否合法, 浮点值, 错误信息)
    """
    try:
        v = float(value.replace(",", ""))
        if v <= 0:
            return False, None, "股数必须大于 0"
        return True, v, ""
    except (ValueError, AttributeError):
        return False, None, f"无效股数：{value}"


def validate_api_key(key: str, name: str) -> tuple[bool, str]:
    """
    基本校验 API Key 非空且长度合理
    返回 (是否合法, 错误信息)
    """
    if not key or not key.strip():
        return False, f"{name} API Key 不能为空"
    key = key.strip()
    if len(key) < 8:
        return False, f"{name} API Key 长度不足（至少 8 个字符）"
    if key in ("your_fmp_api_key_here", "your_finnhub_api_key_here",
               "your_alpha_vantage_key_here", "your_deepseek_api_key_here"):
        return False, f"请填写真实的 {name} API Key"
    return True, ""


def validate_date_range(start: str, end: str) -> tuple[bool, str]:
    """
    校验日期范围 YYYY-MM-DD 格式且 start <= end
    返回 (是否合法, 错误信息)
    """
    from datetime import date
    fmt = "%Y-%m-%d"
    try:
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        if s > e:
            return False, f"开始日期 {start} 不能晚于结束日期 {end}"
        return True, ""
    except ValueError as exc:
        return False, f"日期格式错误：{exc}（格式要求：YYYY-MM-DD）"
