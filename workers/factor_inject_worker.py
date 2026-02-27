"""
因子注入 Worker（Phase A + B + C）
- 后台执行 RD-Agent 因子 IC 验证
- 持久化通过验证的因子到 ~/.quantbyqlib/valid_factors.json
- 清除模型预测缓存，使下次选股自动重新训练（含自定义因子）
- 通过 EventBus 广播 rdagent_factors_injected 信号
"""
from __future__ import annotations

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal


class FactorInjectSignals(QObject):
    progress  = pyqtSignal(int, str)   # (pct, message)
    completed = pyqtSignal(list)        # list[str] 通过验证的因子表达式
    error     = pyqtSignal(str)         # 错误信息


class FactorInjectWorker(QRunnable):
    """
    在线程池中后台执行因子注入流程：
      1. 检查 Qlib 是否就绪
      2. 从 RD-Agent 最新会话读取因子
      3. IC 验证（Spearman ≥ 0.03）
      4. 持久化有效因子
      5. 清除模型预测缓存
      6. 发送完成信号 + EventBus 广播
    """

    def __init__(self, min_ic: float = 0.03):
        super().__init__()
        self.min_ic  = min_ic
        self.signals = FactorInjectSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        from loguru import logger

        def cb(pct: int, msg: str) -> None:
            self.signals.progress.emit(pct, msg)

        try:
            cb(2, "初始化 Qlib...")
            from strategies.qlib_strategy import _qlib_init_check
            _qlib_init_check()

            cb(5, "读取 RD-Agent 历史会话...")
            from strategies.factor_injector import get_valid_factors, save_valid_factors
            valid_exprs = get_valid_factors(
                min_ic=self.min_ic,
                progress_cb=cb,
            )

            cb(97, f"持久化 {len(valid_exprs)} 个有效因子...")
            save_valid_factors(valid_exprs)

            # 清除模型缓存，确保下次选股重新训练（含新因子）
            if valid_exprs:
                try:
                    from strategies.model_cache import clear_cache
                    n = clear_cache()
                    logger.info(f"[因子注入] 清除 {n} 个旧模型缓存")
                except Exception as e:
                    logger.debug(f"[因子注入] 清除缓存失败（忽略）：{e}")

            # EventBus 广播
            try:
                from core.event_bus import get_event_bus
                get_event_bus().rdagent_factors_injected.emit(valid_exprs)
            except Exception as e:
                logger.debug(f"[因子注入] EventBus 广播失败（忽略）：{e}")

            cb(100, f"完成：{len(valid_exprs)} 个因子通过验证")
            self.signals.completed.emit(valid_exprs)

        except Exception as e:
            from loguru import logger as _log
            _log.exception(f"[因子注入] Worker 异常：{e}")
            self.signals.error.emit(str(e))
