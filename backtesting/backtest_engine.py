"""
回测引擎
直接复用 Qlib 的 R（工作流记录器）+ SignalRecord + PortAnaRecord
同时支持简化模式（仅用价格序列做轻量回测，不依赖完整 Qlib workflow）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import numpy as np
from loguru import logger

from backtesting.performance_metrics import (
    BacktestMetrics, calc_metrics_from_returns
)


@dataclass
class BacktestConfig:
    """回测配置"""
    strategy_key:  str
    start_date:    str
    end_date:      str
    topk:          int   = 50
    n_drop:        int   = 5          # TopkDropout 每期换出数量
    hold_thresh:   float = 0.5        # 持有阈值
    init_capital:  float = 1_000_000  # 初始资金（美元）
    benchmark:     str   = "SPY"      # 基准指数


@dataclass
class BacktestReport:
    """回测完整报告"""
    config:     BacktestConfig
    metrics:    BacktestMetrics
    nav_series: pd.Series              # 净值曲线（index=date, value=净值）
    bm_series:  pd.Series              # 基准净值曲线
    ic_series:  pd.Series              # IC 时间序列
    positions_history: list[dict] = field(default_factory=list)
    available:  bool = True
    error:      Optional[str] = None


class BacktestEngine:
    """
    回测引擎
    优先使用 Qlib workflow（完整）
    Qlib 未初始化时使用简化价格回测
    """

    def run(self, config: BacktestConfig,
            progress_cb=None) -> BacktestReport:
        """执行回测，返回 BacktestReport"""
        self._cb(progress_cb, 5, "初始化回测引擎...")

        from core.app_state import get_state
        if get_state().qlib_initialized:
            return self._run_qlib_backtest(config, progress_cb)
        else:
            logger.warning("Qlib 未初始化，使用简化价格回测")
            return self._run_simple_backtest(config, progress_cb)

    # ── Qlib 完整回测 ─────────────────────────────────────────

    def _run_qlib_backtest(self, config: BacktestConfig,
                            progress_cb=None) -> BacktestReport:
        """使用 Qlib R 记录器 + SignalRecord + PortAnaRecord"""
        self._cb(progress_cb, 10, "构建 Qlib 数据集...")

        try:
            from strategies.qlib_strategy import get_strategy
            from qlib.contrib.strategy import TopkDropoutStrategy
            from qlib.contrib.evaluate import risk_analysis
            from qlib.workflow import R
            from qlib.workflow.record_temp import SignalRecord, PortAnaRecord

            strategy = get_strategy(config.strategy_key, topk=config.topk)

            # 构建数据集（训练窗口扩展到回测起始日前一年）
            from strategies.qlib_strategy import _build_dataset
            start_dt = date.fromisoformat(config.start_date)
            ext_start = (start_dt - timedelta(days=365)).isoformat()

            self._cb(progress_cb, 20, "训练模型...")

            # 获取股票宇宙
            from screening.stock_screener import StockScreener
            screener = StockScreener()
            universe = screener._from_qlib() or screener._sp500_fallback()

            dataset = _build_dataset(universe[:500], "Alpha158",
                                     train_days=365, pred_days=30)

            from qlib.contrib.model.gbdt import LGBModel
            model = LGBModel(num_leaves=64, num_threads=4)
            model.fit(dataset)

            self._cb(progress_cb, 50, "运行 Qlib SignalRecord...")

            with R.start(experiment_name=f"backtest_{config.strategy_key}"):
                recorder = R.get_recorder()
                sr = SignalRecord(model=model, dataset=dataset, recorder=recorder)
                sr.generate()

                self._cb(progress_cb, 65, "运行 PortAnaRecord（组合分析）...")

                qlib_strategy = TopkDropoutStrategy(
                    signal=sr.load("pred.pkl"),
                    topk=config.topk,
                    n_drop=config.n_drop,
                )
                par = PortAnaRecord(
                    recorder=recorder,
                    config={
                        "strategy": qlib_strategy,
                        "backtest": {
                            "start_time": config.start_date,
                            "end_time":   config.end_date,
                            "account":    config.init_capital,
                            "benchmark":  config.benchmark,
                            "exchange_kwargs": {"freq": "day", "limit_threshold": 0.095},
                        },
                    },
                )
                par.generate()

                self._cb(progress_cb, 80, "提取回测指标...")

                # 读取结果
                analysis = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")
                ic_df    = recorder.load_object("sig_analysis/ic.pkl")

            nav_series = self._extract_nav(analysis, config.init_capital)
            bm_series  = self._fetch_benchmark_nav(
                config.benchmark, config.start_date, config.end_date
            )
            ic_series  = ic_df["IC"] if ic_df is not None and "IC" in ic_df else pd.Series(dtype=float)

            returns = nav_series.pct_change().dropna()
            bm_ret  = bm_series.pct_change().dropna() if not bm_series.empty else None
            metrics = calc_metrics_from_returns(
                returns, bm_ret, start_date=config.start_date, end_date=config.end_date
            )
            # 补充 IC 指标
            if not ic_series.empty:
                metrics.ic_mean = float(ic_series.mean())
                metrics.ic_std  = float(ic_series.std())
                metrics.icir    = metrics.ic_mean / metrics.ic_std \
                                  if metrics.ic_std and metrics.ic_std > 0 else None

            self._cb(progress_cb, 100, "回测完成")

            return BacktestReport(
                config=config,
                metrics=metrics,
                nav_series=nav_series,
                bm_series=bm_series,
                ic_series=ic_series,
                available=True,
            )

        except Exception as e:
            logger.warning(f"Qlib 完整回测失败，降级到简化模式：{e}")
            return self._run_simple_backtest(config, progress_cb)

    # ── 简化价格回测（不依赖 Qlib workflow）──────────────────

    # 每种策略对应的打分因子权重 & 持仓特征
    _STRATEGY_PROFILES: dict = {
        "growth_stocks":       {"mom20": 0.2, "mom60": 0.5, "mom252": 0.3, "vol_filter": False},
        "market_adaptive":     {"mom20": 0.3, "mom60": 0.4, "mom252": 0.2, "vol_filter": True},
        "deep_learning":       {"mom20": 0.4, "mom60": 0.3, "mom252": 0.3, "vol_filter": False},
        "intraday_profit":     {"mom20": 0.7, "mom60": 0.3, "mom252": 0.0, "vol_filter": True},
        "pytorch_full_market": {"mom20": 0.3, "mom60": 0.4, "mom252": 0.3, "vol_filter": False},
    }

    def _run_simple_backtest(self, config: BacktestConfig,
                              progress_cb=None) -> BacktestReport:
        """
        简化回测（Qlib 未初始化时）：
        1. 在回测起始日之前的一段"选股窗口"内，用价格因子打分选出 Top-K 组合
        2. 下载该组合在回测区间的完整历史价格
        3. 模拟等权持有、计算净值曲线与绩效指标
        不同策略使用不同的因子权重，使结果有真实差异。
        """
        self._cb(progress_cb, 10, "根据策略特征选股...")

        from screening.stock_screener import StockScreener
        screener = StockScreener()
        universe = screener._sp500_fallback()   # ~100 支大盘股宇宙

        # ── 1. 选股阶段：用回测开始日前 6 个月数据打分 ──────────
        score_end   = config.start_date
        score_start = (date.fromisoformat(config.start_date) - timedelta(days=180)).isoformat()

        self._cb(progress_cb, 15, f"下载选股窗口价格（{score_start} → {score_end}）...")
        score_prices = self._fetch_prices_batch(universe, score_start, score_end)

        if score_prices is None or score_prices.empty:
            # 选股窗口无数据时退化为全宇宙等权
            selected = universe[:config.topk]
            logger.warning("选股窗口数据不足，使用全宇宙等权")
        else:
            selected = self._select_by_strategy(
                score_prices, config.strategy_key, config.topk
            )

        self._cb(progress_cb, 35, f"已选出 {len(selected)} 支股票，下载回测区间价格...")

        # ── 2. 下载回测区间价格 ─────────────────────────────────
        price_df = self._fetch_prices_batch(
            selected, config.start_date, config.end_date, progress_cb
        )

        if price_df is None or price_df.empty:
            return BacktestReport(
                config=config,
                metrics=BacktestMetrics(
                    start_date=config.start_date,
                    end_date=config.end_date
                ),
                nav_series=pd.Series(dtype=float),
                bm_series=pd.Series(dtype=float),
                ic_series=pd.Series(dtype=float),
                available=False,
                error="价格数据不可用（所有数据源失败）",
            )

        # ── 3. 计算等权组合净值 ──────────────────────────────────
        self._cb(progress_cb, 70, "计算等权组合收益...")
        daily_ret    = price_df.pct_change().dropna()
        portfolio_ret = daily_ret.mean(axis=1)   # 等权

        # ── 4. 基准数据 ──────────────────────────────────────────
        self._cb(progress_cb, 80, "获取 S&P500 基准数据...")
        bm_prices = self._fetch_single_price(
            config.benchmark, config.start_date, config.end_date
        )
        bm_ret = bm_prices.pct_change().dropna() if bm_prices is not None else None

        nav_series = (1 + portfolio_ret).cumprod()
        bm_series  = (1 + bm_ret).cumprod() if bm_ret is not None else pd.Series(dtype=float)

        metrics = calc_metrics_from_returns(
            portfolio_ret, bm_ret,
            start_date=config.start_date,
            end_date=config.end_date
        )

        self._cb(progress_cb, 100, "回测完成（简化模式）")
        logger.info(
            f"简化回测 [{config.strategy_key}] 选出 {len(selected)} 支："
            f"年化={metrics.annual_return:.1%}，"
            f"Sharpe={metrics.sharpe_ratio:.2f}"
        )

        return BacktestReport(
            config=config,
            metrics=metrics,
            nav_series=nav_series,
            bm_series=bm_series,
            ic_series=pd.Series(dtype=float),   # 简化模式无 IC
            available=True,
        )

    def _select_by_strategy(self, price_df: pd.DataFrame,
                             strategy_key: str, topk: int) -> list[str]:
        """
        按策略特征对股票打分，返回 Top-K 列表。
        不同策略使用不同的动量周期权重，确保回测结果真实有差异。
        """
        profile = self._STRATEGY_PROFILES.get(
            strategy_key,
            {"mom20": 0.33, "mom60": 0.33, "mom252": 0.34, "vol_filter": False},
        )
        scores: dict[str, float] = {}

        for ticker in price_df.columns:
            try:
                col = price_df[ticker]
                # 确保是 1-D Series（防止 MultiIndex 列意外带入 2-D 数据）
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                close = col.dropna()
                if len(close) < 20:
                    continue

                # 辅助函数：安全取标量值
                def _scalar(val):
                    if isinstance(val, pd.Series):
                        val = val.iloc[0]
                    return float(val)

                s = 0.0
                weight_total = 0.0

                w20 = profile["mom20"]
                if w20 > 0 and len(close) >= 20:
                    mom20 = _scalar(close.iloc[-1]) / _scalar(close.iloc[-20]) - 1
                    s += w20 * np.clip(mom20 * 5 + 0.5, 0.0, 1.0)
                    weight_total += w20

                w60 = profile["mom60"]
                if w60 > 0 and len(close) >= 60:
                    mom60 = _scalar(close.iloc[-1]) / _scalar(close.iloc[-60]) - 1
                    s += w60 * np.clip(mom60 * 3 + 0.5, 0.0, 1.0)
                    weight_total += w60
                elif w60 > 0 and len(close) >= 20:
                    # 数据不足 60 天，用 mom20 代替
                    mom20 = _scalar(close.iloc[-1]) / _scalar(close.iloc[-20]) - 1
                    s += w60 * np.clip(mom20 * 5 + 0.5, 0.0, 1.0)
                    weight_total += w60

                w252 = profile["mom252"]
                if w252 > 0 and len(close) >= 120:
                    lookback = min(len(close) - 1, 252)
                    mom252 = _scalar(close.iloc[-1]) / _scalar(close.iloc[-lookback]) - 1
                    s += w252 * np.clip(mom252 * 1.5 + 0.5, 0.0, 1.0)
                    weight_total += w252

                if weight_total > 0:
                    final_score = s / weight_total

                    # 波动率过滤：intraday_profit / market_adaptive 偏好低波动
                    if profile["vol_filter"] and len(close) >= 20:
                        vol = float(close.pct_change().dropna().tail(20).std())
                        # 高波动打折扣（日波动 >3% 开始扣分）
                        vol_penalty = max(0.0, 1.0 - (vol - 0.03) * 10) if vol > 0.03 else 1.0
                        final_score *= vol_penalty

                    scores[ticker] = final_score

            except Exception as e:
                logger.debug(f"[backtest select] {ticker} 打分失败：{e}")
                continue

        if not scores:
            return list(price_df.columns[:topk])

        sorted_tickers = sorted(scores, key=lambda t: scores[t], reverse=True)
        return sorted_tickers[:topk]

    # ── 私有工具方法 ──────────────────────────────────────────

    def _fetch_prices_batch(self, tickers: list[str],
                             start: str, end: str,
                             progress_cb=None) -> Optional[pd.DataFrame]:
        """批量获取收盘价（以 ticker 为列），用 yfinance 一次性批量下载"""
        self._cb(progress_cb, 30, f"批量下载 {len(tickers)} 支股票价格...")
        try:
            import yfinance as yf
            # yfinance 一次下载所有 ticker，速度远快于逐一下载
            tickers_str = " ".join(tickers)
            df_all = yf.download(
                tickers_str,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
            )
            if df_all is None or df_all.empty:
                raise ValueError("yfinance 批量下载返回空数据")

            # 提取 Close 列
            if isinstance(df_all.columns, pd.MultiIndex):
                # 多股票：MultiIndex (指标, ticker)
                if "Close" in df_all.columns.get_level_values(0):
                    close_df = df_all["Close"]
                else:
                    level0 = df_all.columns.get_level_values(0)[0]
                    close_df = df_all[level0]
            else:
                # 单股票：扁平列
                close_col = next(
                    (c for c in df_all.columns if str(c).lower() in ("close", "adj close", "adj_close")),
                    None
                )
                if close_col is None:
                    raise ValueError("找不到 Close 列")
                close_df = df_all[[close_col]].rename(columns={close_col: tickers[0]})

            close_df = close_df.dropna(how="all")
            close_df.index = pd.to_datetime(close_df.index)

            # 过滤数据量不足的列
            min_rows = max(5, len(close_df) // 4)
            close_df = close_df.loc[:, close_df.notna().sum() >= min_rows]

            if close_df.empty:
                raise ValueError("所有股票数据不足")

            self._cb(progress_cb, 45, f"批量下载完成，{close_df.shape[1]} 支有效数据")
            return close_df

        except Exception as e:
            logger.warning(f"yfinance 批量下载失败（{e}），降级为逐一下载...")

        # 降级：逐一下载
        frames = {}
        for i, ticker in enumerate(tickers):
            pct = 30 + int(i / len(tickers) * 40)
            if i % 5 == 0:
                self._cb(progress_cb, pct, f"下载价格 {i+1}/{len(tickers)}...")
            series = self._fetch_single_price(ticker, start, end)
            if series is not None and not series.empty:
                frames[ticker] = series

        if not frames:
            return None
        return pd.DataFrame(frames).sort_index()

    def _fetch_single_price(self, ticker: str,
                             start: str, end: str) -> Optional[pd.Series]:
        """获取单只股票收盘价序列，优先 yfinance 直接调用，失败时走 OpenBB"""
        # 1. yfinance 直接获取（最可靠，无需 API Key）
        try:
            import yfinance as yf
            df = yf.download(ticker, start=start, end=end,
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                # yfinance >= 0.2 返回 MultiIndex 列时处理
                if hasattr(df.columns, "levels"):
                    df.columns = df.columns.get_level_values(0)
                close_col = next(
                    (c for c in df.columns if str(c).lower() in ("close", "adj close", "adj_close")),
                    None
                )
                if close_col and not df[close_col].dropna().empty:
                    s = df[close_col].dropna()
                    s.index = pd.to_datetime(s.index)
                    return s
        except Exception as e:
            logger.debug(f"yfinance 直接获取 {ticker} 失败：{e}")

        # 2. OpenBB fallback
        try:
            from data.openbb_client import get_price_history
            result = get_price_history(ticker, start, end)
            if result and result.results:
                df = result.to_dataframe()
                close_col = next(
                    (c for c in df.columns if str(c).lower() in ("close", "adj_close", "adj close")),
                    None
                )
                if close_col:
                    s = df[close_col].dropna()
                    s.index = pd.to_datetime(s.index)
                    return s
        except Exception as e:
            logger.debug(f"OpenBB 获取 {ticker} 失败：{e}")

        return None

    def _fetch_benchmark_nav(self, benchmark: str,
                              start: str, end: str) -> pd.Series:
        """获取基准净值曲线"""
        prices = self._fetch_single_price(benchmark, start, end)
        if prices is None or prices.empty:
            return pd.Series(dtype=float)
        nav = prices / prices.iloc[0]
        return nav

    def _extract_nav(self, analysis, init_capital: float) -> pd.Series:
        """从 Qlib PortAnaRecord 结果提取净值曲线"""
        try:
            if hasattr(analysis, "account_value"):
                nav = analysis.account_value / init_capital
                return nav
            if isinstance(analysis, pd.DataFrame) and "account" in analysis.columns:
                return analysis["account"] / init_capital
        except Exception:
            pass
        return pd.Series(dtype=float)

    def _cb(self, cb, pct: int, msg: str) -> None:
        if cb:
            try:
                cb(pct, msg)
            except Exception:
                pass
        logger.debug(f"[Backtest] {pct}% - {msg}")
