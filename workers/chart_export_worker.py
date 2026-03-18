"""
持仓 K 线图批量导出 Worker
对每支持仓股票生成 5日/日线/周线 三张 PNG，保存到指定目录
"""
from __future__ import annotations

from pathlib import Path
from PyQt6.QtCore import QRunnable, QObject, pyqtSignal


class ChartExportSignals(QObject):
    progress  = pyqtSignal(int, str)   # (pct, message)
    completed = pyqtSignal(str)        # 导出目录路径
    error     = pyqtSignal(str)


class ChartExportWorker(QRunnable):
    """
    批量导出 K 线图到 output_dir。
    tickers: 股票代码列表
    output_dir: 保存目录（Path）
    """

    _PERIOD_PARAMS = {
        "5d":   dict(period="5d",   interval="5m",  label="5D Chart"),
        "day":  dict(period="60d",  interval="1d",  label="Daily"),
        "week": dict(period="104wk",interval="1wk", label="Weekly"),
    }

    def __init__(self, tickers: list[str], output_dir: Path):
        super().__init__()
        self.tickers    = tickers
        self.output_dir = output_dir
        self.signals    = ChartExportSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        from loguru import logger

        try:
            import yfinance as yf
            import mplfinance as mpf
            import matplotlib
            matplotlib.use("Agg")   # 无 GUI 后端，适合后台导出

            self.output_dir.mkdir(parents=True, exist_ok=True)

            import matplotlib.pyplot as plt
            for _font in ["PingFang HK", "PingFang SC", "STHeiti", "Heiti TC", "Arial Unicode MS"]:
                try:
                    plt.rcParams["font.family"] = _font
                    break
                except Exception:
                    continue
            plt.rcParams["axes.unicode_minus"] = False

            total = len(self.tickers) * len(self._PERIOD_PARAMS)
            done  = 0

            style = mpf.make_mpf_style(
                base_mpf_style="charles",
                marketcolors=mpf.make_marketcolors(
                    up="#22C55E", down="#EF4444",
                    edge="inherit", wick="inherit",
                    volume={"up": "#22C55E88", "down": "#EF444488"},
                ),
                figcolor="#FFFFFF",
                gridcolor="#E2E4EA",
                gridstyle="--",
            )

            for ticker in self.tickers:
                for period_key, params in self._PERIOD_PARAMS.items():
                    label = params["label"]
                    msg   = f"正在导出 {ticker} {label}..."
                    pct   = int(done / total * 95) if total > 0 else 0
                    self.signals.progress.emit(pct, msg)

                    try:
                        # 优先长桥，fallback yfinance
                        df = None
                        src = "yfinance"
                        try:
                            from data.longport_client import get_candlesticks, is_configured
                            if is_configured():
                                df = get_candlesticks(ticker, period_key)
                                if df is not None and not df.empty:
                                    src = "LongPort"
                        except Exception:
                            pass

                        if df is None or df.empty:
                            df = yf.download(
                                ticker, progress=False, auto_adjust=True,
                                period=params["period"], interval=params["interval"],
                            )
                            if df is not None and not df.empty:
                                if hasattr(df.columns, "levels"):
                                    df.columns = df.columns.get_level_values(0)
                                df.index.name = "Date"

                        if df is None or df.empty:
                            logger.warning(f"[图表导出] {ticker} {label} 无数据，跳过")
                            done += 1
                            continue

                        title = f"{ticker}  {label}  [{src}]"
                        save_path = self.output_dir / f"{ticker}_{period_key}.png"

                        fig, _ = mpf.plot(
                            df,
                            type="candle",
                            style=style,
                            title=title,
                            volume=True,
                            returnfig=True,
                            figsize=(12, 7),
                            tight_layout=True,
                        )
                        fig.savefig(str(save_path), dpi=150, bbox_inches="tight")
                        import matplotlib.pyplot as plt
                        plt.close(fig)
                        logger.info(f"[图表导出] 已保存：{save_path}")

                    except Exception as e:
                        logger.warning(f"[图表导出] {ticker} {label} 失败：{e}")

                    done += 1

            self.signals.progress.emit(100, f"导出完成，共 {done} 张图表")
            self.signals.completed.emit(str(self.output_dir))

        except Exception as e:
            from loguru import logger as _log
            _log.exception(f"[图表导出] Worker 异常：{e}")
            self.signals.error.emit(str(e))
