"""
回测性能指标计算
从 Qlib SignalRecord / PortAnaRecord 的输出中提取关键指标
支持独立计算（不依赖 Qlib R 记录器）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class BacktestMetrics:
    """回测性能指标"""
    # 收益指标
    annual_return:   Optional[float] = None   # 年化收益率
    total_return:    Optional[float] = None   # 总收益率
    # 风险指标
    sharpe_ratio:    Optional[float] = None   # Sharpe 比率（年化）
    max_drawdown:    Optional[float] = None   # 最大回撤（负值）
    volatility:      Optional[float] = None   # 年化波动率
    # 信息系数
    ic_mean:         Optional[float] = None   # IC 均值
    ic_std:          Optional[float] = None   # IC 标准差
    icir:            Optional[float] = None   # ICIR = IC / IC_std
    # 胜率
    win_rate:        Optional[float] = None   # 胜率（正收益天数/总天数）
    # 对比基准
    alpha:           Optional[float] = None   # 相对 S&P500 超额收益
    beta:            Optional[float] = None   # Beta 值
    # 时间范围
    start_date:      Optional[str]   = None
    end_date:        Optional[str]   = None
    trading_days:    Optional[int]   = None


def calc_metrics_from_returns(returns: pd.Series,
                               benchmark_returns: Optional[pd.Series] = None,
                               rf_rate: float = 0.045,
                               start_date: str = "",
                               end_date:   str = "") -> BacktestMetrics:
    """
    从日收益率序列计算全套指标
    returns:           策略日收益率（小数，如 0.012 = 1.2%）
    benchmark_returns: 基准日收益率（S&P500）
    rf_rate:           无风险利率（年化），默认 4.5%（美联储利率）
    """
    if returns is None or len(returns) < 10:
        return BacktestMetrics(start_date=start_date, end_date=end_date)

    returns = returns.dropna()
    n = len(returns)
    trading_days_per_year = 252

    # ── 收益指标 ──
    total_return  = float((1 + returns).prod() - 1)
    years         = n / trading_days_per_year
    annual_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else 0.0

    # ── 风险指标 ──
    daily_std  = float(returns.std())
    volatility = daily_std * np.sqrt(trading_days_per_year)

    # Sharpe Ratio
    daily_rf   = rf_rate / trading_days_per_year
    excess     = returns - daily_rf
    sharpe     = float(excess.mean() / excess.std() * np.sqrt(trading_days_per_year)) \
                 if excess.std() > 0 else 0.0

    # 最大回撤
    cum_returns  = (1 + returns).cumprod()
    rolling_max  = cum_returns.cummax()
    drawdown     = (cum_returns - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # 胜率
    win_rate = float((returns > 0).mean())

    # ── Alpha / Beta（需要基准） ──
    alpha = None
    beta  = None
    if benchmark_returns is not None and len(benchmark_returns) > 10:
        bm = benchmark_returns.reindex(returns.index).dropna()
        common = returns.reindex(bm.index).dropna()
        bm = bm.reindex(common.index)
        if len(common) > 10:
            cov_matrix = np.cov(common, bm)
            beta_val   = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 1.0
            alpha_daily = float(common.mean() - beta_val * bm.mean())
            alpha = alpha_daily * trading_days_per_year
            beta  = float(beta_val)

    return BacktestMetrics(
        annual_return=annual_return,
        total_return=total_return,
        sharpe_ratio=sharpe,
        max_drawdown=max_drawdown,
        volatility=volatility,
        win_rate=win_rate,
        alpha=alpha,
        beta=beta,
        start_date=start_date,
        end_date=end_date,
        trading_days=n,
    )


def calc_ic_from_predictions(pred_scores: pd.Series,
                              actual_returns: pd.Series) -> dict[str, Optional[float]]:
    """
    计算 IC（信息系数）
    IC = Spearman 秩相关（预测分数 vs 实际收益）
    """
    try:
        from scipy.stats import spearmanr
        common_idx = pred_scores.index.intersection(actual_returns.index)
        if len(common_idx) < 10:
            return {"ic_mean": None, "ic_std": None, "icir": None}

        corr, _ = spearmanr(
            pred_scores.reindex(common_idx),
            actual_returns.reindex(common_idx)
        )
        ic_mean = float(corr)
        # 对单截面 IC 只有 mean，std/ICIR 需要时间序列多截面
        return {"ic_mean": ic_mean, "ic_std": None, "icir": None}
    except Exception as e:
        logger.debug(f"IC 计算失败：{e}")
        return {"ic_mean": None, "ic_std": None, "icir": None}


def calc_ic_series(pred_df: pd.DataFrame,
                   return_df: pd.DataFrame) -> pd.Series:
    """
    计算时间序列 IC
    pred_df:   MultiIndex(date, ticker) → score
    return_df: MultiIndex(date, ticker) → return
    返回: Series(index=date, values=IC)
    """
    from scipy.stats import spearmanr

    ic_list = []
    for date in pred_df.index.get_level_values(0).unique():
        try:
            pred = pred_df.xs(date, level=0)
            ret  = return_df.xs(date, level=0) if date in return_df.index else None
            if ret is None or len(pred) < 5:
                continue
            common = pred.index.intersection(ret.index)
            if len(common) < 5:
                continue
            corr, _ = spearmanr(pred.reindex(common), ret.reindex(common))
            ic_list.append((date, float(corr)))
        except Exception:
            continue

    if not ic_list:
        return pd.Series(dtype=float)

    ic_series = pd.Series(
        [v for _, v in ic_list],
        index=[d for d, _ in ic_list]
    )
    return ic_series
