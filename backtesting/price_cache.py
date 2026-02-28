"""
回测价格数据磁盘缓存
避免每次回测重复下载 yfinance 价格数据。
缓存目录：~/.quantbyqlib/price_cache/
TTL 策略：历史数据（>30天前）永久有效；近期数据按天失效。
"""
from __future__ import annotations

import hashlib
import pickle
import time
from datetime import date
from pathlib import Path
from typing import Optional, Union

import pandas as pd
from loguru import logger

CACHE_DIR = Path.home() / ".quantbyqlib" / "price_cache"


def price_cache_key(tickers: list[str], start: str, end: str) -> str:
    """
    生成价格缓存键（MD5 前12位）。
    tickers 排序后 hash，确保顺序无关。
    """
    tickers_str = ",".join(sorted(tickers))
    raw = f"price_batch|{tickers_str}|{start}|{end}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _get_ttl_hours(end_date_str: str) -> float:
    """
    根据 end_date 距今天数计算合适的 TTL（小时）：
    - end_date 在 7 天内：4 小时（近期数据每日更新）
    - end_date 在 30 天内：24 小时
    - end_date 超过 30 天：inf（历史数据永不过期）
    """
    try:
        end_dt = date.fromisoformat(end_date_str)
        days_ago = (date.today() - end_dt).days
        if days_ago <= 7:
            return 4.0
        elif days_ago <= 30:
            return 24.0
        else:
            return float("inf")
    except Exception:
        return 24.0  # 解析失败时保守策略


def load_prices(
    key: str, max_age_hours: float = 24.0
) -> Optional[Union[pd.DataFrame, pd.Series]]:
    """
    从缓存加载价格数据。
    返回 DataFrame（批量）或 Series（单支），过期或不存在返回 None。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.pkl"

    if not cache_file.exists():
        return None

    age_seconds = time.time() - cache_file.stat().st_mtime
    age_hours = age_seconds / 3600.0

    if max_age_hours != float("inf") and age_hours > max_age_hours:
        logger.debug(f"价格缓存已过期（{age_hours:.1f}h > {max_age_hours}h）：{key}")
        return None

    try:
        with open(cache_file, "rb") as f:
            data = pickle.load(f)
        if not isinstance(data, (pd.DataFrame, pd.Series)):
            return None
        shape_info = data.shape if isinstance(data, pd.DataFrame) else f"({len(data)},)"
        logger.info(f"命中价格缓存（{age_hours:.1f}h 前）：{key}，形状={shape_info}")
        return data
    except Exception as e:
        logger.debug(f"价格缓存读取失败：{e}")
        return None


def save_prices(key: str, data: Union[pd.DataFrame, pd.Series]) -> None:
    """将价格数据保存到缓存（失败静默处理，不影响主流程）。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.pkl"

    try:
        with open(cache_file, "wb") as f:
            pickle.dump(data, f)
        shape_info = data.shape if isinstance(data, pd.DataFrame) else f"({len(data)},)"
        logger.info(f"已缓存价格数据 {shape_info}：{key}")
    except Exception as e:
        logger.warning(f"价格缓存写入失败：{e}")


def clear_price_cache() -> int:
    """清除所有价格缓存文件，返回删除数量。"""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    logger.info(f"已清除 {count} 个价格缓存文件")
    return count


def price_cache_info() -> dict:
    """返回缓存目录统计信息。"""
    if not CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0.0, "dir": str(CACHE_DIR)}
    files = list(CACHE_DIR.glob("*.pkl"))
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "count": len(files),
        "size_mb": round(total_bytes / 1e6, 2),
        "dir": str(CACHE_DIR),
    }
