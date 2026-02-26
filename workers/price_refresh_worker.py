"""
持仓价格批量刷新 Worker
定期从 OpenBB 获取持仓股票的最新报价，更新 UI
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class PriceRefreshSignals(QObject):
    prices_updated = pyqtSignal(dict)   # {symbol: {price, change_pct, ...}}
    error          = pyqtSignal(str)


class PriceRefreshWorker(QRunnable):
    """批量刷新持仓股票最新价格"""

    def __init__(self, tickers: list[str]):
        super().__init__()
        self.tickers = tickers
        self.signals = PriceRefreshSignals()
        self.setAutoDelete(True)

    @pyqtSlot()
    def run(self) -> None:
        if not self.tickers:
            self.signals.prices_updated.emit({})
            return

        try:
            from data.openbb_client import get_batch_quotes
            quotes = get_batch_quotes(self.tickers)
            # 过滤掉 None
            result = {k: v for k, v in quotes.items() if v is not None}
            logger.debug(f"价格刷新完成：{len(result)}/{len(self.tickers)} 支有数据")
            self.signals.prices_updated.emit(result)
        except Exception as e:
            logger.warning(f"价格刷新失败：{e}")
            self.signals.error.emit(str(e))
            self.signals.prices_updated.emit({})
