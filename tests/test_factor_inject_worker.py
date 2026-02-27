"""
factor_inject_worker 单元测试
所有外部依赖均为 lazy import，patch 需用原始模块路径。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThreadPool, QEventLoop, QTimer

_app = QApplication.instance() or QApplication(sys.argv)


def _run_worker_sync(worker, timeout_ms: int = 8000):
    result = {"signal": None, "payload": None}
    loop = QEventLoop()

    def on_completed(data):
        result["signal"] = "completed"
        result["payload"] = data
        loop.quit()

    def on_error(msg):
        result["signal"] = "error"
        result["payload"] = msg
        loop.quit()

    worker.signals.completed.connect(on_completed)
    worker.signals.error.connect(on_error)
    QTimer.singleShot(timeout_ms, loop.quit)
    QThreadPool.globalInstance().start(worker)
    loop.exec()
    return result


# ──────────────────────────────────────────────────────────────
#  辅助：patch factor_inject_worker 所有 lazy import 依赖
# ──────────────────────────────────────────────────────────────

def _worker_patches(
    valid_exprs=None,
    qlib_init_error=None,
    get_valid_factors_error=None,
    clear_cache_error=None,
    eventbus_error=None,
):
    """
    返回上下文管理器列表，完整 mock factor_inject_worker.run() 的所有 lazy import。
    """
    from contextlib import ExitStack

    if valid_exprs is None:
        valid_exprs = []

    stack = ExitStack()
    mocks = {}

    # strategies.qlib_strategy._qlib_init_check
    if qlib_init_error:
        stack.enter_context(
            patch("strategies.qlib_strategy._qlib_init_check",
                  side_effect=qlib_init_error)
        )
    else:
        stack.enter_context(
            patch("strategies.qlib_strategy._qlib_init_check")
        )

    # strategies.factor_injector.get_valid_factors
    if get_valid_factors_error:
        stack.enter_context(
            patch("strategies.factor_injector.get_valid_factors",
                  side_effect=get_valid_factors_error)
        )
    else:
        stack.enter_context(
            patch("strategies.factor_injector.get_valid_factors",
                  return_value=valid_exprs)
        )

    # strategies.factor_injector.save_valid_factors
    save_mock = stack.enter_context(
        patch("strategies.factor_injector.save_valid_factors")
    )
    mocks["save"] = save_mock

    # strategies.model_cache.clear_cache
    if clear_cache_error:
        clear_mock = stack.enter_context(
            patch("strategies.model_cache.clear_cache",
                  side_effect=clear_cache_error)
        )
    else:
        clear_mock = stack.enter_context(
            patch("strategies.model_cache.clear_cache",
                  return_value=2)
        )
    mocks["clear"] = clear_mock

    # core.event_bus.get_event_bus
    mock_bus = MagicMock()
    if eventbus_error:
        mock_bus.rdagent_factors_injected.emit.side_effect = eventbus_error
    stack.enter_context(
        patch("core.event_bus.get_event_bus", return_value=mock_bus)
    )
    mocks["bus"] = mock_bus

    return stack, mocks


# ──────────────────────────────────────────────────────────────
#  1. 正常完成流程
# ──────────────────────────────────────────────────────────────
class TestFactorInjectWorkerSuccess(unittest.TestCase):

    def test_complete_flow_emits_completed_signal(self):
        valid_exprs = ["Ref($close,5)/$close-1", "$volume/Ref($volume,10)-1"]
        stack, _ = _worker_patches(valid_exprs=valid_exprs)
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "completed")
        self.assertEqual(res["payload"], valid_exprs)

    def test_empty_factors_does_not_clear_cache(self):
        stack, mocks = _worker_patches(valid_exprs=[])
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "completed")
        self.assertEqual(res["payload"], [])
        mocks["clear"].assert_not_called()

    def test_valid_factors_triggers_cache_clear(self):
        stack, mocks = _worker_patches(valid_exprs=["expr_a"])
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            _run_worker_sync(worker)

        mocks["clear"].assert_called_once()

    def test_eventbus_signal_emitted(self):
        valid_exprs = ["expr_x"]
        stack, mocks = _worker_patches(valid_exprs=valid_exprs)
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            _run_worker_sync(worker)

        mocks["bus"].rdagent_factors_injected.emit.assert_called_once_with(valid_exprs)

    def test_save_valid_factors_called_with_result(self):
        valid_exprs = ["expr1", "expr2"]
        stack, mocks = _worker_patches(valid_exprs=valid_exprs)
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            _run_worker_sync(worker)

        mocks["save"].assert_called_once_with(valid_exprs)

    def test_progress_signals_emitted(self):
        progress_events = []
        stack, _ = _worker_patches(valid_exprs=[])
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            worker.signals.progress.connect(
                lambda pct, msg: progress_events.append(pct)
            )
            _run_worker_sync(worker)

        self.assertGreaterEqual(len(progress_events), 2)
        self.assertEqual(progress_events[-1], 100)


# ──────────────────────────────────────────────────────────────
#  2. 异常处理
# ──────────────────────────────────────────────────────────────
class TestFactorInjectWorkerError(unittest.TestCase):

    def test_qlib_init_failure_emits_error(self):
        stack, _ = _worker_patches(
            qlib_init_error=RuntimeError("Qlib 未就绪")
        )
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "error")
        self.assertIn("Qlib", res["payload"])

    def test_get_valid_factors_failure_emits_error(self):
        stack, _ = _worker_patches(
            get_valid_factors_error=ValueError("会话读取失败")
        )
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "error")
        self.assertIn("会话读取失败", res["payload"])

    def test_eventbus_failure_does_not_crash(self):
        """EventBus 异常不影响 completed 信号"""
        stack, _ = _worker_patches(
            valid_exprs=["expr"],
            eventbus_error=RuntimeError("Bus error"),
        )
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "completed")

    def test_clear_cache_failure_does_not_crash(self):
        """clear_cache 异常不影响 completed 信号"""
        stack, _ = _worker_patches(
            valid_exprs=["expr"],
            clear_cache_error=OSError("disk error"),
        )
        with stack:
            from workers.factor_inject_worker import FactorInjectWorker
            worker = FactorInjectWorker(min_ic=0.03)
            res = _run_worker_sync(worker)

        self.assertEqual(res["signal"], "completed")


# ──────────────────────────────────────────────────────────────
#  3. 信号/结构测试
# ──────────────────────────────────────────────────────────────
class TestFactorInjectWorkerSignals(unittest.TestCase):

    def test_signals_attributes_exist(self):
        from workers.factor_inject_worker import FactorInjectSignals
        sig = FactorInjectSignals()
        self.assertTrue(hasattr(sig, "progress"))
        self.assertTrue(hasattr(sig, "completed"))
        self.assertTrue(hasattr(sig, "error"))

    def test_worker_has_signals(self):
        from workers.factor_inject_worker import FactorInjectWorker
        worker = FactorInjectWorker()
        self.assertIsNotNone(worker.signals)

    def test_worker_auto_delete(self):
        from workers.factor_inject_worker import FactorInjectWorker
        worker = FactorInjectWorker()
        self.assertTrue(worker.autoDelete())

    def test_default_min_ic(self):
        from workers.factor_inject_worker import FactorInjectWorker
        worker = FactorInjectWorker()
        self.assertEqual(worker.min_ic, 0.03)

    def test_custom_min_ic(self):
        from workers.factor_inject_worker import FactorInjectWorker
        worker = FactorInjectWorker(min_ic=0.05)
        self.assertEqual(worker.min_ic, 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
