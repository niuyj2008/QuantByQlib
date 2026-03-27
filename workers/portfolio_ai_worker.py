"""
持仓 AI 批量分析 Worker
依次对每个持仓股票运行 StockAnalyzer + LLMReportGenerator，
将 Markdown 报告保存到本地，并通过信号向 UI 汇报进度。
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class PortfolioAISignals(QObject):
    # (current_index, total, ticker, status_text)
    progress  = pyqtSignal(int, int, str, str)
    # (ticker, saved_path)  单支完成
    one_done  = pyqtSignal(str, str)
    # (success_list, fail_list, reports_dir)
    all_done  = pyqtSignal(list, list, str)
    error     = pyqtSignal(str, str)          # ticker, error_message


class PortfolioAIWorker(QRunnable):
    """
    批量 AI 分析 Worker。
    tickers: 持仓股票代码列表（顺序执行，避免并发 API 过载）
    """

    def __init__(self, tickers: list[str]):
        super().__init__()
        self._tickers = [t.upper().strip() for t in tickers if t.strip()]
        self.signals  = PortfolioAISignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        total      = len(self._tickers)
        success    = []
        failed     = []
        reports_dir = ""

        for idx, ticker in enumerate(self._tickers, start=1):
            self.signals.progress.emit(idx, total, ticker, f"正在分析 {ticker}…")

            try:
                # ── 1. 基本面 + 技术面分析 ──────────────────────────
                from stock_analysis.stock_analyzer import StockAnalyzer
                self.signals.progress.emit(idx, total, ticker, f"[{ticker}] 获取基本面与技术数据…")
                report = StockAnalyzer().analyze(ticker)

                # ── 2. LLM 流式生成报告（收集完整文本）─────────────
                from stock_analysis.llm_report_generator import LLMReportGenerator
                self.signals.progress.emit(idx, total, ticker, f"[{ticker}] AI 生成报告…")
                generator  = LLMReportGenerator()
                full_text  = ""
                for chunk in generator.generate_stream(report):
                    full_text += chunk

                # ── 3. 保存 MD 文件 ──────────────────────────────────
                saved_path = ""
                if full_text:
                    from services.report_writer import ReportWriter
                    from pathlib import Path
                    path_obj   = ReportWriter().save_stock_report(ticker, full_text)
                    saved_path = str(path_obj)
                    reports_dir = str(Path(saved_path).parent.parent)

                success.append(ticker)
                self.signals.one_done.emit(ticker, saved_path or "")
                logger.info(f"[PortfolioAIWorker] {ticker} AI 报告生成完成：{saved_path}")

            except Exception as e:
                logger.error(f"[PortfolioAIWorker] {ticker} 失败：{e}")
                failed.append(ticker)
                self.signals.error.emit(ticker, str(e))

        self.signals.all_done.emit(success, failed, reports_dir)
