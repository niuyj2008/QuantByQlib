"""
Qlib 模型预测分数缓存（24小时有效）
避免每次选股都重新训练模型（LightGBM ~30秒，LSTM ~10分钟）
缓存目录：~/.quantbyqlib/model_cache/
"""
from __future__ import annotations

import hashlib
import pickle
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

CACHE_DIR = Path.home() / ".quantbyqlib" / "model_cache"


def cache_key(strategy_key: str, universe: list[str], data_end: object) -> str:
    """
    生成缓存键（md5 前12位）
    strategy_key: 策略标识
    universe: 股票池列表（排序后 hash）
    data_end: Qlib 数据最新日期（date 对象或字符串）
    """
    universe_str = ",".join(sorted(universe))
    raw = f"{strategy_key}|{universe_str}|{data_end}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def load_scores(key: str, max_age_hours: float = 24.0) -> Optional[pd.Series]:
    """
    从缓存加载预测分数
    返回 pd.Series（ticker→score），若缓存不存在或已过期则返回 None
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.pkl"

    if not cache_file.exists():
        return None

    age_seconds = time.time() - cache_file.stat().st_mtime
    age_hours = age_seconds / 3600.0

    if age_hours > max_age_hours:
        logger.debug(f"缓存已过期（{age_hours:.1f}h > {max_age_hours}h）：{key}")
        return None

    try:
        with open(cache_file, "rb") as f:
            scores = pickle.load(f)
        if not isinstance(scores, pd.Series):
            return None
        logger.info(f"命中缓存（{age_hours:.1f}h 前）：{key}，共 {len(scores)} 支股票")
        return scores
    except Exception as e:
        logger.debug(f"缓存读取失败：{e}")
        return None


def save_scores(key: str, scores: pd.Series) -> None:
    """
    将预测分数保存到缓存
    scores: pd.Series（ticker→score）
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{key}.pkl"

    try:
        with open(cache_file, "wb") as f:
            pickle.dump(scores, f)
        logger.info(f"已缓存预测分数（{len(scores)} 支股票）：{key}")
    except Exception as e:
        logger.warning(f"缓存写入失败：{e}")


def clear_cache() -> int:
    """清除所有缓存文件，返回删除数量"""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.glob("*.pkl"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    logger.info(f"已清除 {count} 个模型缓存文件")
    return count


def cache_info() -> dict:
    """返回缓存目录统计信息"""
    if not CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0.0, "dir": str(CACHE_DIR)}
    files = list(CACHE_DIR.glob("*.pkl"))
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "count": len(files),
        "size_mb": round(total_bytes / 1e6, 2),
        "dir": str(CACHE_DIR),
    }
