"""
信号胜率验证 Worker
在 QThreadPool 中运行 SignalValidator，完成后通过信号通知 UI。
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class SignalValidateSignals(QObject):
    progress  = pyqtSignal(int, str)     # pct, message
    result    = pyqtSignal(object)       # ValidationResult
    error     = pyqtSignal(str)          # error_message


class SignalValidateWorker(QRunnable):
    """
    历史信号胜率验证 Worker。
    lookback_days: 向前查看多少天的信号文件（默认 60）
    """

    def __init__(self, lookback_days: int = 60):
        super().__init__()
        self.lookback_days = lookback_days
        self.signals = SignalValidateSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.progress.emit(10, "扫描历史信号文件...")
            from backtesting.signal_validator import SignalValidator
            validator = SignalValidator()

            self.signals.progress.emit(30, f"加载过去 {self.lookback_days} 天的买入信号...")
            result = validator.validate(
                lookback_days=self.lookback_days,
                forward_days=[5, 20],
            )

            self.signals.progress.emit(90, f"已验证 {result.validated} 条信号，计算完成")
            self.signals.result.emit(result)

        except Exception as e:
            logger.error(f"[SignalValidateWorker] 失败：{e}")
            self.signals.error.emit(str(e))
