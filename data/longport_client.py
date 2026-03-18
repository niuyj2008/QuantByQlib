"""
长桥（LongPort）行情数据封装
支持：
  - 5日图：Min_5 分钟K线（最近 5 × 78 根）
  - 日线：Day K（最近 60 根）
  - 周线：Week K（最近 104 根）

返回 pandas DataFrame，列名与 mplfinance 兼容：
  Open / High / Low / Close / Volume，Index 为 DatetimeTZInfo
"""
from __future__ import annotations

import os
import pandas as pd
from datetime import datetime
from typing import Optional


def _get_config():
    """从环境变量构建长桥 Config，缺少任意 Key 则返回 None"""
    from longport.openapi import Config
    app_key    = os.environ.get("LONGPORT_APP_KEY", "").strip()
    app_secret = os.environ.get("LONGPORT_APP_SECRET", "").strip()
    access_tok = os.environ.get("LONGPORT_ACCESS_TOKEN", "").strip()
    if not (app_key and app_secret and access_tok):
        return None
    return Config(
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_tok,
    )


def is_configured() -> bool:
    """检查长桥 Key 是否已配置"""
    return _get_config() is not None


def get_candlesticks(ticker: str, period_key: str) -> Optional[pd.DataFrame]:
    """
    拉取 K 线数据并返回 mplfinance 兼容 DataFrame。

    period_key:
      "5d"   → Min_5，最近 390 根（约 5 个交易日 × 78 根/天）
      "day"  → Day，  最近 60 根
      "week" → Week， 最近 104 根

    symbol 格式：长桥要求 "AAPL.US"（美股后缀 .US）
    """
    cfg = _get_config()
    if cfg is None:
        return None

    try:
        from longport.openapi import QuoteContext, Period, AdjustType

        _PERIOD_MAP = {
            "5d":   (Period.Min_5, 390),
            "day":  (Period.Day,    60),
            "week": (Period.Week,  104),
        }
        period, count = _PERIOD_MAP[period_key]

        # 长桥 symbol 格式
        symbol = ticker if "." in ticker else f"{ticker}.US"

        ctx = QuoteContext(cfg)
        candles = ctx.candlesticks(
            symbol=symbol,
            period=period,
            count=count,
            adjust_type=AdjustType.ForwardAdjust,
        )

        if not candles:
            return None

        rows = []
        for c in candles:
            rows.append({
                "Date":   c.timestamp,
                "Open":   float(c.open),
                "High":   float(c.high),
                "Low":    float(c.low),
                "Close":  float(c.close),
                "Volume": int(c.volume),
            })

        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df.index.name = "Date"
        return df

    except Exception as e:
        from loguru import logger
        logger.warning(f"[长桥] 拉取 {ticker} {period_key} 失败：{e}")
        return None
