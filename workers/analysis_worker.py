"""
个股综合分析后台 Worker
在 QThreadPool 中运行 StockAnalyzer，完成后通过信号通知 UI
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class AnalysisSignals(QObject):
    """Worker 信号"""
    started  = pyqtSignal(str)                  # ticker
    result   = pyqtSignal(str, object)           # ticker, StockReport
    error    = pyqtSignal(str, str)              # ticker, error_message
    progress = pyqtSignal(str, int, str)         # ticker, pct(0-100), status_text


class AnalysisWorker(QRunnable):
    """
    个股分析 Worker
    ticker:           股票代码
    use_deep_model:   是否使用 DistilBERT 精准情绪模型（默认 VADER）
    price_period_days:K线数据天数（默认 365）
    """

    def __init__(self, ticker: str,
                 use_deep_model: bool = False,
                 price_period_days: int = 365):
        super().__init__()
        self.ticker           = ticker.upper().strip()
        self.use_deep_model   = use_deep_model
        self.price_period_days = price_period_days
        self.signals          = AnalysisSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        ticker = self.ticker
        self.signals.started.emit(ticker)

        try:
            self.signals.progress.emit(ticker, 10, "初始化分析模块...")

            from stock_analysis.stock_analyzer import StockAnalyzer
            analyzer = StockAnalyzer()

            self.signals.progress.emit(ticker, 20, "并行获取 Alpha158 + K线 + 基本面 + 情绪...")

            report = analyzer.analyze(
                ticker,
                use_deep_sentiment=self.use_deep_model,
                price_period_days=self.price_period_days,
            )

            self.signals.progress.emit(ticker, 95, "生成综合报告...")
            self.signals.result.emit(ticker, report)
            self.signals.progress.emit(ticker, 100, "分析完成")

            logger.info(
                f"AnalysisWorker [{ticker}] 完成，"
                f"综合评分={report.overall.score}"
            )

        except Exception as e:
            logger.error(f"AnalysisWorker [{ticker}] 异常：{e}")
            self.signals.error.emit(ticker, str(e))
