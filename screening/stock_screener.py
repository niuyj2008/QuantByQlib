"""
股票筛选器
1. 从 Qlib 数据中获取可用股票（宇宙）
2. 调用策略运行选股
3. 用 OpenBB 补充当日涨跌幅（用于结果展示）
"""
from __future__ import annotations

from typing import Optional, Callable
from loguru import logger

from strategies.base_strategy import StrategyResult


class StockScreener:
    """股票筛选器：宇宙构建 → 策略运行 → 结果丰富"""

    def __init__(self):
        self._universe_cache: Optional[list[str]] = None

    def run(self,
            strategy_key: str,
            topk: Optional[int] = None,
            universe: Optional[list[str]] = None,
            progress_cb: Optional[Callable] = None) -> list[dict]:
        """
        执行选股流程
        返回 [{ticker, score, signal, change_pct, strategy, ...}]
        """
        self._cb(progress_cb, 5, "获取股票宇宙...")

        # 1. 获取候选股票池
        candidates = universe or self._get_universe(progress_cb)
        if not candidates:
            raise RuntimeError("股票宇宙为空，请确认 Qlib 数据已下载")

        self._cb(progress_cb, 15, f"股票池：{len(candidates)} 支，开始运行策略...")

        # 2. 运行策略
        from strategies.qlib_strategy import get_strategy

        def strategy_progress(pct: int, msg: str):
            # 策略进度映射到总进度 15-85%
            total_pct = 15 + int(pct * 0.70)
            self._cb(progress_cb, total_pct, msg)

        strategy = get_strategy(strategy_key, topk=topk)
        result: StrategyResult = strategy.run(candidates, progress_cb=strategy_progress)

        self._cb(progress_cb, 87, "获取当日涨跌幅（OpenBB）...")

        # 3. 获取涨跌幅
        price_map = self._batch_get_changes(result.topk_tickers)

        self._cb(progress_cb, 95, "整理选股结果...")

        # 4. 构建结果列表
        output = []
        for ticker in result.topk_tickers:
            score = float(result.scores.get(ticker, 0.0))
            change_pct = price_map.get(ticker)

            # 信号判断
            signal = self._score_to_signal(score, result.scores)

            output.append({
                "ticker":       ticker,
                "score":        score,
                "signal":       signal,
                "change_pct":   change_pct,    # None 表示无数据
                "strategy":     result.strategy_name,
                "strategy_key": result.strategy_key,
                "model":        result.model_name,
                "universe_size":result.universe_size,
            })

        logger.info(
            f"选股完成：策略={strategy_key}，"
            f"从 {result.universe_size} 支中选出 {len(output)} 支"
        )
        return output

    # ── 宇宙构建 ──────────────────────────────────────────────

    def _get_universe(self, progress_cb=None) -> list[str]:
        """
        获取股票宇宙：
        优先从 Qlib 已有数据中读取（确保有 Alpha158 数据可用）
        """
        if self._universe_cache:
            return self._universe_cache

        # 从 Qlib 数据中获取可用股票
        tickers = self._from_qlib()
        if tickers:
            self._universe_cache = tickers
            return tickers

        # Qlib 未初始化时，使用 S&P500 精简版
        logger.warning("Qlib 数据不可用，使用内置 S&P500 精简宇宙")
        tickers = self._sp500_fallback()
        self._universe_cache = tickers
        return tickers

    def _from_qlib(self) -> list[str]:
        """从 Qlib 数据中提取有效股票（有 features/ 数据的）"""
        try:
            from qlib.data import D
            from qlib.config import C

            instruments = D.instruments(market="all")
            df = D.list_instruments(instruments, start_time="-30d", end_time="today",
                                    as_list=True)
            tickers = [str(t).upper() for t in df if t]
            logger.info(f"Qlib 宇宙：{len(tickers)} 支股票")
            return tickers[:2000]   # 限制防止 OOM（全市场可能 5000+）
        except Exception as e:
            logger.debug(f"Qlib 宇宙获取失败：{e}")
            return []

    def _sp500_fallback(self) -> list[str]:
        """内置精简宇宙（约 100 支大盘股），仅作备用"""
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK.B",
            "UNH", "JNJ", "XOM", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK",
            "ABBV", "PEP", "KO", "AVGO", "COST", "MCD", "WMT", "ACN", "BAC",
            "ADBE", "CRM", "NEE", "TMO", "ORCL", "ABT", "NFLX", "DHR", "QCOM",
            "TXN", "PM", "WFC", "RTX", "UPS", "LIN", "AMGN", "SBUX", "HON",
            "IBM", "ELV", "MDLZ", "GILD", "CVS", "AMD", "INTC", "NOW", "INTU",
            "CAT", "BA", "GS", "MS", "BLK", "AXP", "SPGI", "CME", "MO", "C",
            "DE", "USB", "MMM", "LOW", "ISRG", "REGN", "VRTX", "LMT", "ZTS",
            "ADI", "CI", "ADP", "BSX", "MRNA", "PLD", "AMT", "CCI", "PSA",
            "EQR", "AVB", "WELL", "DLR", "SPG", "BXP", "ESS", "MAA", "UDR",
            "CPT", "EXR", "IRM", "PEAK", "VICI", "MGM", "WYNN", "LVS", "CZR",
        ]

    # ── 工具方法 ──────────────────────────────────────────────

    def _batch_get_changes(self, tickers: list[str]) -> dict[str, Optional[float]]:
        """批量获取今日涨跌幅"""
        try:
            from data.openbb_client import get_batch_quotes
            quotes = get_batch_quotes(tickers)
            return {
                t: q.get("change_pct") if q else None
                for t, q in quotes.items()
            }
        except Exception as e:
            logger.warning(f"批量涨跌幅获取失败：{e}")
            return {t: None for t in tickers}

    def _score_to_signal(self, score: float, all_scores) -> str:
        """
        根据分数在宇宙中的相对排名判断信号
        Top 10% → BUY，Bottom 20% → SELL，其余 → HOLD
        """
        try:
            import numpy as np
            percentile = float(
                (all_scores < score).sum() / len(all_scores) * 100
            )
            if percentile >= 90:
                return "BUY"
            elif percentile >= 70:
                return "HOLD"
            else:
                return "WATCH"
        except Exception:
            return "HOLD"

    def _cb(self, cb, pct: int, msg: str) -> None:
        if cb:
            try:
                cb(pct, msg)
            except Exception:
                pass
