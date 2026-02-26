"""
RD-Agent 后台 Worker
在 QRunnable 中启动 RDAgentRunner，通过事件总线向 UI 推送进度
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, pyqtSlot
from loguru import logger


class RDAgentSignals(QObject):
    log       = pyqtSignal(str)    # 日志行
    completed = pyqtSignal(list)   # list[dict] 发现的因子
    failed    = pyqtSignal(str)    # 错误信息
    stopped   = pyqtSignal()       # 用户主动停止


class RDAgentWorker(QRunnable):
    """
    RD-Agent 启动 Worker。
    注意：日志流式读取在 RDAgentRunner._stream_loop 的子线程中运行，
    本 Worker 仅负责启动并在主线程安全地中继信号。
    """

    def __init__(self):
        super().__init__()
        self.signals = RDAgentSignals()
        self._runner = None
        self.setAutoDelete(True)

    def cancel(self) -> None:
        """请求停止（UI 线程调用）"""
        if self._runner:
            self._runner.stop()
        logger.info("RDAgentWorker 收到取消请求")

    @pyqtSlot()
    def run(self) -> None:
        logger.info("RDAgentWorker 开始")

        try:
            from rdagent_integration.rdagent_runner import RDAgentRunner

            def on_log(line: str) -> None:
                self.signals.log.emit(line)
                # 同步到事件总线
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().rdagent_log.emit(line)
                except Exception:
                    pass

            def on_done(factors: list) -> None:
                self.signals.completed.emit(factors)
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().rdagent_completed.emit(factors)
                except Exception:
                    pass

            def on_error(err: str) -> None:
                self.signals.failed.emit(err)
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().rdagent_failed.emit(err)
                except Exception:
                    pass

            self._runner = RDAgentRunner(
                log_cb=on_log,
                done_cb=on_done,
                error_cb=on_error,
            )

            # 通知已启动
            try:
                from core.event_bus import get_event_bus
                get_event_bus().rdagent_started.emit()
            except Exception:
                pass

            ok = self._runner.start()
            if not ok:
                # start() 内部已通过 error_cb 通知，这里静默退出
                return

            # 等待日志流子线程完成
            if self._runner._thread:
                self._runner._thread.join()

            # 判断是否是用户主动停止
            if self._runner._stop_event.is_set():
                self.signals.stopped.emit()
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().rdagent_stopped.emit()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"RDAgentWorker 异常：{e}")
            self.signals.failed.emit(str(e))
            try:
                from core.event_bus import get_event_bus
                get_event_bus().rdagent_failed.emit(str(e))
            except Exception:
                pass
