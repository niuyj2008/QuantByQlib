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

    # 精选大盘股（S&P500 核心成分 + 纳斯达克100主力），
    # 在 Qlib 数据集中均有完整历史，适合 Alpha158 因子计算
    _CORE_UNIVERSE = [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","TSLA","BRK-B","UNH",
        "JPM","V","XOM","LLY","JNJ","MA","AVGO","PG","HD","MRK","COST","ABBV",
        "CVX","KO","PEP","WMT","ACN","MCD","BAC","CRM","ORCL","ADBE","AMD","NFLX",
        "QCOM","TXN","INTU","AMGN","CSCO","NOW","INTC","IBM","GS","CAT","HON",
        "RTX","LOW","GE","SPGI","BKNG","ISRG","ELV","AXP","CB","SYK","PLD","BLK",
        "VRTX","C","DE","REGN","ADI","LRCX","KLAC","MRVL","MU","PANW","SNPS","CDNS",
        "ANET","FTNT","CRWD","ZS","DDOG","TEAM","WDAY","VEEV","HUBS","COUP","ZM",
        "SHOP","SQ","PYPL","COIN","HOOD","PLTR","RBLX","U","DASH","LYFT","UBER",
        "ABNB","AIRB","BMRN","BIIB","GILD","MRNA","BNTX","PFE","AZN","LMT","NOC",
        "GD","BA","HII","L3HARRIS","LDOS","BAH","SAIC","MANT","CACI","MAXR",
        "WFC","MS","USB","PNC","TFC","COF","AIG","MET","PRU","AFL","ALL","TRV",
        "SPG","O","AMT","CCI","DLR","PSA","WELL","EQR","AVB","PLD","VTR","HR",
        "VZ","T","TMUS","CMCSA","DIS","NFLX","PARA","WBD","FOX","NWS",
        "XOM","CVX","COP","SLB","HAL","BKR","DVN","MPC","VLO","PSX","OXY",
        "NEE","DUK","SO","D","AEP","EXC","XEL","ED","PEG","AWK",
        "LIN","APD","ECL","SHW","PPG","NEM","FCX","AA","CLF","NUE","STLD",
        "UPS","FDX","DAL","UAL","AAL","LUV","CSX","NSC","UNP","WAB",
        "CVS","WBA","MCK","CAH","ABC","HCA","THC","CNC","MOH","HUM",
        "WMT","TGT","COST","HD","LOW","BBY","ROST","TJX","DG","DLTR",
        "SBUX","MCD","YUM","CMG","DPZ","QSR","DKNG","PENN",
        "BA","CAT","DE","HON","GE","MMM","EMR","ROK","PH","ETN","IR","XYL",
        "TSCO","SYF","WEX","CSGP","COIN","FIS","FISV","GPN","MA","V","AXP",
    ]

    def _from_qlib(self) -> list[str]:
        """
        从 Qlib 美股数据 features/ 目录枚举有效股票，
        优先返回有完整历史数据的核心大盘股（适合 Alpha158 ML 训练），
        再补充其他有效股票，过滤退市/数据稀少的股票。
        """
        try:
            from data.qlib_manager import _find_us_data_dir
            data_dir = _find_us_data_dir()
        except Exception:
            from pathlib import Path
            data_dir = Path.home() / ".qlib" / "qlib_data"

        features_dir = data_dir / "features"
        if not features_dir.exists():
            logger.debug(f"features/ 目录不存在：{features_dir}")
            return []

        # 检查哪些核心大盘股在 Qlib 数据中存在且有效
        core_valid = []
        for ticker in self._CORE_UNIVERSE:
            ticker_dir = features_dir / ticker.lower()
            close_bin = ticker_dir / "close.day.bin"
            if close_bin.exists() and close_bin.stat().st_size > 4004:
                core_valid.append(ticker)

        # 再枚举其余有效股票作为补充
        core_set = {t.lower() for t in core_valid}
        extra = []
        for d in features_dir.iterdir():
            if not d.is_dir():
                continue
            name = d.name
            if name in core_set:
                continue
            if any(name.lower().startswith(pfx) for pfx in ("sh", "sz", "bj", "^", "_")):
                continue
            if not name.replace("-", "").replace(".", "").isalnum():
                continue
            close_bin = d / "close.day.bin"
            if not close_bin.exists() or close_bin.stat().st_size < 4004:
                continue
            extra.append(name.upper())

        tickers = core_valid + sorted(extra)
        logger.info(
            f"Qlib 美股宇宙：{len(tickers)} 支（核心大盘股 {len(core_valid)} 支优先，来自 {data_dir}）"
        )
        return tickers[:2000]

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
        """批量获取今日涨跌幅，优先用 yfinance 一次性批量请求"""
        if not tickers:
            return {}
        try:
            import yfinance as yf
            import pandas as pd
            # 一次性批量下载最近 2 天，计算涨跌幅
            symbols = " ".join(tickers)
            df = yf.download(
                symbols,
                period="2d",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
            if df is None or df.empty:
                return {t: None for t in tickers}

            result: dict[str, Optional[float]] = {}
            for ticker in tickers:
                try:
                    if isinstance(df.columns, pd.MultiIndex):
                        if ticker not in df.columns.get_level_values(0):
                            result[ticker] = None
                            continue
                        closes = df[ticker]["Close"].dropna()
                    else:
                        closes = df["Close"].dropna()

                    if len(closes) >= 2:
                        pct = float((closes.iloc[-1] / closes.iloc[-2] - 1) * 100)
                        result[ticker] = round(pct, 2)
                    else:
                        result[ticker] = None
                except Exception:
                    result[ticker] = None
            return result
        except Exception as e:
            logger.warning(f"yfinance 批量涨跌幅获取失败：{e}，尝试 OpenBB...")

        # 降级：OpenBB
        try:
            from data.openbb_client import get_batch_quotes
            quotes = get_batch_quotes(tickers)
            return {
                t: q.get("change_pct") if q else None
                for t, q in quotes.items()
            }
        except Exception as e:
            logger.warning(f"OpenBB 涨跌幅获取失败：{e}")
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
