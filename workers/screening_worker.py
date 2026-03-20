"""
量化选股后台 Worker
在 QThreadPool 中运行 StockScreener，完成后通过事件总线通知 UI
支持取消（设置 _cancelled 标志）
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class ScreeningSignals(QObject):
    progress  = pyqtSignal(int, str)      # pct, message
    completed = pyqtSignal(list)          # list[dict] 选股结果
    failed    = pyqtSignal(str)           # error message


class ScreeningWorker(QRunnable):
    """
    量化选股 Worker
    strategy_key:  策略标识符（growth_stocks / market_adaptive / ...）
    topk:          选出数量（None 使用策略默认值）
    universe:      候选股票列表（None 从 Qlib 自动获取）
    """

    def __init__(self,
                 strategy_key: str,
                 topk: Optional[int] = None,
                 universe: Optional[list[str]] = None):
        super().__init__()
        self.strategy_key = strategy_key
        self.topk         = topk
        self.universe     = universe
        self.signals      = ScreeningSignals()
        self._cancelled   = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        """请求取消（在下一个检查点生效）"""
        self._cancelled = True
        logger.info(f"ScreeningWorker [{self.strategy_key}] 取消请求")

    @pyqtSlot()
    def run(self) -> None:
        logger.info(f"ScreeningWorker 开始：strategy={self.strategy_key}，topk={self.topk}")

        def progress_cb(pct: int, msg: str):
            if self._cancelled:
                raise InterruptedError("用户取消")
            self.signals.progress.emit(pct, msg)

        try:
            from screening.stock_screener import StockScreener
            screener = StockScreener()

            results = screener.run(
                strategy_key=self.strategy_key,
                topk=self.topk,
                universe=self.universe,
                progress_cb=progress_cb,
            )

            if self._cancelled:
                self.signals.failed.emit("用户取消")
                return

            self.signals.progress.emit(100, f"✅ 完成，选出 {len(results)} 支")
            self.signals.completed.emit(results)

            # 同步到事件总线（让其他页面监听）
            try:
                from core.event_bus import get_event_bus
                bus = get_event_bus()
                bus.screening_completed.emit(results)
            except Exception:
                pass

            # 自动写入规范化信号 CSV 到「美股交易日记/signals/」
            try:
                from services.signal_exporter import export_signals, export_signals_empty
                sig_path = export_signals(self.strategy_key, results) if results \
                    else export_signals_empty(self.strategy_key)
                logger.info(f"ScreeningWorker [{self.strategy_key}] 信号 CSV → {sig_path}")
            except Exception as ex:
                logger.warning(
                    f"ScreeningWorker [{self.strategy_key}] 信号 CSV 写入失败（非致命）：{ex}"
                )

            logger.info(f"ScreeningWorker [{self.strategy_key}] 完成，{len(results)} 支")

        except InterruptedError as e:
            self.signals.failed.emit(str(e))
            try:
                from core.event_bus import get_event_bus
                get_event_bus().screening_failed.emit(str(e))
            except Exception:
                pass

        except Exception as e:
            logger.error(f"ScreeningWorker [{self.strategy_key}] 异常：{e}")
            self.signals.failed.emit(str(e))
            try:
                from core.event_bus import get_event_bus
                get_event_bus().screening_failed.emit(str(e))
            except Exception:
                pass
