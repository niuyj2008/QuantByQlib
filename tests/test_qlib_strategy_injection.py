"""
qlib_strategy 因子注入集成测试
测试 _fit_with_extra_factors 和 _run_with_qlib_or_fallback 中的注入逻辑。
所有外部依赖均 mock，不需要真实数据。

注意：qlib_strategy.py 中的依赖为 lazy import（函数内 from ... import）。
patch 时使用原始模块路径，并在需要时直接操作模块对象属性。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────
#  辅助
# ──────────────────────────────────────────────────────────────

def _make_dataset_mock():
    """返回行为完整的 mock DatasetH"""
    instruments = ["aapl", "msft", "nvda"]
    dates       = pd.date_range("2024-01-02", periods=60, freq="B")
    idx         = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    n = len(idx)

    feat_cols = pd.MultiIndex.from_tuples([("feature", f"f{i}") for i in range(5)])
    data      = np.random.randn(n, 5)
    base_df   = pd.DataFrame(data, index=idx, columns=feat_cols)
    base_df[("label", "ret")] = np.random.randn(n)

    def _prepare(segments, col_set=None, data_key=None, **kwargs):
        if isinstance(segments, str):
            return base_df.copy()
        return {s: base_df.copy() for s in segments}

    dataset          = MagicMock()
    dataset.prepare  = _prepare
    return dataset


def _make_pred_series(instruments=None):
    instruments = instruments or ["aapl", "msft", "nvda"]
    dt  = pd.Timestamp("2026-02-26")
    idx = pd.MultiIndex.from_product(
        [[dt], instruments], names=["datetime", "instrument"]
    )
    return pd.Series(np.random.rand(len(instruments)), index=idx)


# ──────────────────────────────────────────────────────────────
#  1. _fit_with_extra_factors
# ──────────────────────────────────────────────────────────────
class TestFitWithExtraFactors(unittest.TestCase):

    def _make_custom_df(self, instruments=None, n_dates=80):
        instruments = instruments or ["aapl", "msft", "nvda"]
        dates = pd.date_range("2024-01-02", periods=n_dates, freq="B")
        idx   = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )
        return pd.DataFrame(
            np.random.randn(len(idx), 2),
            index=idx,
            columns=["_extra_0", "_extra_1"],
        )

    def test_model_fit_called_when_data_available(self):
        """D.features 成功时 model.fit 应被调用一次"""
        dataset   = _make_dataset_mock()
        fit_calls = []
        model     = MagicMock()
        model.fit = lambda d, **kw: fit_calls.append(d)

        custom_df = self._make_custom_df()

        with patch("qlib.data.D") as mock_D:
            mock_D.features.return_value = custom_df
            from strategies.qlib_strategy import _fit_with_extra_factors
            _fit_with_extra_factors(
                model, dataset,
                ["Ref($close,5)/$close-1"],
                ["aapl", "msft", "nvda"],
                "2024-01-02", "2024-09-01",
            )

        self.assertEqual(len(fit_calls), 1)

    def test_prepare_restored_after_fit(self):
        """fit 完成后 dataset.prepare 应恢复为原始方法"""
        dataset          = _make_dataset_mock()
        original_prepare = dataset.prepare
        fit_calls        = []
        model            = MagicMock()
        model.fit        = lambda d, **kw: fit_calls.append(d)

        custom_df = self._make_custom_df()

        with patch("qlib.data.D") as mock_D:
            mock_D.features.return_value = custom_df
            from strategies.qlib_strategy import _fit_with_extra_factors
            _fit_with_extra_factors(
                model, dataset,
                ["$volume/$close"],
                ["aapl", "msft"],
                "2024-01-02", "2024-09-01",
            )

        self.assertEqual(dataset.prepare, original_prepare)

    def test_d_features_failure_still_calls_model_fit(self):
        """D.features 失败时应 fallback 到普通 model.fit"""
        dataset   = _make_dataset_mock()
        fit_calls = []
        model     = MagicMock()
        model.fit = lambda d, **kw: fit_calls.append(d)

        with patch("qlib.data.D") as mock_D:
            mock_D.features.side_effect = RuntimeError("Qlib error")
            from strategies.qlib_strategy import _fit_with_extra_factors
            _fit_with_extra_factors(
                model, dataset,
                ["bad_expression"],
                ["aapl"],
                "2024-01-02", "2024-09-01",
            )

        self.assertEqual(len(fit_calls), 1)

    def test_empty_custom_df_falls_back_to_normal_fit(self):
        """D.features 返回空 DataFrame 时应 fallback"""
        dataset   = _make_dataset_mock()
        fit_calls = []
        model     = MagicMock()
        model.fit = lambda d, **kw: fit_calls.append(d)

        with patch("qlib.data.D") as mock_D:
            mock_D.features.return_value = pd.DataFrame()
            from strategies.qlib_strategy import _fit_with_extra_factors
            _fit_with_extra_factors(
                model, dataset,
                ["$close"],
                ["aapl"],
                "2024-01-02", "2024-09-01",
            )

        self.assertEqual(len(fit_calls), 1)

    def test_prepare_restored_even_if_fit_raises(self):
        """fit() 抛异常时 dataset.prepare 也应被恢复"""
        dataset          = _make_dataset_mock()
        original_prepare = dataset.prepare
        model            = MagicMock()
        model.fit        = MagicMock(side_effect=RuntimeError("fit crash"))

        custom_df = self._make_custom_df()

        with patch("qlib.data.D") as mock_D:
            mock_D.features.return_value = custom_df
            from strategies.qlib_strategy import _fit_with_extra_factors
            with self.assertRaises(RuntimeError):
                _fit_with_extra_factors(
                    model, dataset,
                    ["$close"],
                    ["aapl"],
                    "2024-01-02", "2024-09-01",
                )

        self.assertEqual(dataset.prepare, original_prepare)


# ──────────────────────────────────────────────────────────────
#  2. _run_with_qlib_or_fallback 因子注入路径
# ──────────────────────────────────────────────────────────────
class TestRunWithQlibOrFallbackInjection(unittest.TestCase):
    """
    _run_with_qlib_or_fallback 内使用 lazy import：
      from strategies.model_cache import cache_key, load_scores, save_scores
      from strategies.factor_injector import load_valid_factors
      from strategies.qlib_strategy import _qlib_init_check (via _qlib_init_check 本身)
    patch 原始模块。
    """

    def _base_patches(self, valid_exprs=None, cached_scores=None,
                      qlib_ok=True, data_end=None):
        """返回基础 patch context，供各测试复用"""
        from contextlib import ExitStack
        stack = ExitStack()

        if data_end is None:
            data_end = date(2026, 2, 26)

        if qlib_ok:
            stack.enter_context(
                patch("strategies.qlib_strategy._qlib_init_check")
            )
        else:
            stack.enter_context(
                patch("strategies.qlib_strategy._qlib_init_check",
                      side_effect=RuntimeError("Qlib 未就绪"))
            )

        stack.enter_context(
            patch("strategies.qlib_strategy._get_qlib_data_end_date",
                  return_value=data_end)
        )
        stack.enter_context(
            patch("strategies.model_cache.cache_key",
                  return_value="test_key_001")
        )
        stack.enter_context(
            patch("strategies.model_cache.load_scores",
                  return_value=cached_scores)
        )
        stack.enter_context(patch("strategies.model_cache.save_scores"))

        if valid_exprs is not None:
            stack.enter_context(
                patch("strategies.factor_injector.load_valid_factors",
                      return_value=valid_exprs)
            )

        return stack

    def test_lgb_strategy_loads_extra_factors(self):
        """growth_stocks（LGB）有有效因子时应调用 _fit_with_extra_factors"""
        dataset = _make_dataset_mock()
        model   = MagicMock()
        model.fit = MagicMock()
        pred    = _make_pred_series()
        model.predict = MagicMock(return_value=pred)

        stack = self._base_patches(valid_exprs=["Ref($close,5)/$close-1"])
        with stack, \
             patch("strategies.qlib_strategy._build_dataset",
                   return_value=dataset), \
             patch("strategies.qlib_strategy._patch_pytorch_model_best_param"), \
             patch("strategies.qlib_strategy._fit_with_extra_factors") as mock_fit_extra:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "growth_stocks", "成长股选股", "Alpha158",
                lambda: model, ["AAPL", "MSFT", "NVDA"],
                topk=10, progress_cb=None,
            )

        mock_fit_extra.assert_called_once()
        model.fit.assert_not_called()   # 普通 fit 不应被调用

    def test_lgb_strategy_no_factors_uses_normal_fit(self):
        """没有有效因子时走普通 model.fit"""
        dataset = _make_dataset_mock()
        model   = MagicMock()
        model.fit = MagicMock()
        pred    = _make_pred_series()
        model.predict = MagicMock(return_value=pred)

        stack = self._base_patches(valid_exprs=[])
        with stack, \
             patch("strategies.qlib_strategy._build_dataset",
                   return_value=dataset), \
             patch("strategies.qlib_strategy._patch_pytorch_model_best_param"), \
             patch("strategies.qlib_strategy._fit_with_extra_factors") as mock_fit_extra:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "growth_stocks", "成长股选股", "Alpha158",
                lambda: model, ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        mock_fit_extra.assert_not_called()
        model.fit.assert_called_once()

    def test_non_lgb_strategy_skips_factor_loading(self):
        """deep_learning（LSTM）不应加载自定义因子"""
        dataset = _make_dataset_mock()
        model   = MagicMock()
        model.fit = MagicMock()
        pred    = _make_pred_series()
        model.predict = MagicMock(return_value=pred)

        load_mock = MagicMock(return_value=["expr"])
        stack = self._base_patches()
        with stack, \
             patch("strategies.factor_injector.load_valid_factors", load_mock), \
             patch("strategies.qlib_strategy._build_dataset",
                   return_value=dataset), \
             patch("strategies.qlib_strategy._patch_pytorch_model_best_param"), \
             patch("strategies.qlib_strategy._fit_with_extra_factors") as mock_fit_extra:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "deep_learning", "深度学习集成", "Alpha158",
                lambda: model, ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        load_mock.assert_not_called()
        mock_fit_extra.assert_not_called()

    def test_cache_hit_skips_training(self):
        """缓存命中时不应构建 dataset（跳过全部训练）"""
        pred_series = pd.Series({"aapl": 0.9, "msft": 0.8})
        stack = self._base_patches(
            valid_exprs=["expr"],
            cached_scores=pred_series,
        )
        with stack, \
             patch("strategies.qlib_strategy._build_dataset") as mock_build:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "growth_stocks", "成长股选股", "Alpha158",
                MagicMock(), ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        mock_build.assert_not_called()

    def test_stale_data_falls_to_yfinance(self):
        """Qlib 数据过旧时应切换 yfinance，不加载因子"""
        ancient_date = date(2010, 1, 1)
        load_mock = MagicMock(return_value=["expr"])

        with patch("strategies.qlib_strategy._qlib_init_check"), \
             patch("strategies.qlib_strategy._get_qlib_data_end_date",
                   return_value=ancient_date), \
             patch("strategies.factor_injector.load_valid_factors", load_mock), \
             patch("strategies.qlib_strategy._yfinance_score_universe",
                   return_value=MagicMock()) as mock_yf:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "growth_stocks", "成长股选股", "Alpha158",
                MagicMock(), ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        load_mock.assert_not_called()
        mock_yf.assert_called_once()

    def test_extra_exprs_change_cache_key(self):
        """有自定义因子时，cache_key 调用的 extra_exprs 参数应非空"""
        dataset = _make_dataset_mock()
        model   = MagicMock()
        model.fit = MagicMock()
        pred    = _make_pred_series()
        model.predict = MagicMock(return_value=pred)

        cache_key_calls = []

        def capture_ck(strategy_key, universe, data_end_arg, extra=None):
            cache_key_calls.append(extra)
            return "captured_key"

        valid_exprs = ["Ref($close,5)/$close-1"]

        with patch("strategies.qlib_strategy._qlib_init_check"), \
             patch("strategies.qlib_strategy._get_qlib_data_end_date",
                   return_value=date(2026, 2, 26)), \
             patch("strategies.model_cache.cache_key",
                   side_effect=capture_ck), \
             patch("strategies.model_cache.load_scores",
                   return_value=None), \
             patch("strategies.model_cache.save_scores"), \
             patch("strategies.factor_injector.load_valid_factors",
                   return_value=valid_exprs), \
             patch("strategies.qlib_strategy._build_dataset",
                   return_value=dataset), \
             patch("strategies.qlib_strategy._patch_pytorch_model_best_param"), \
             patch("strategies.qlib_strategy._fit_with_extra_factors"):

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "growth_stocks", "成长股选股", "Alpha158",
                lambda: model, ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        # 至少有一次调用包含非空 extra
        self.assertTrue(
            any(e for e in cache_key_calls if e),
            "cache_key 应传入非空 extra_exprs"
        )

    def test_market_adaptive_also_loads_factors(self):
        """market_adaptive 也是 LGB 策略，应加载因子"""
        dataset = _make_dataset_mock()
        model   = MagicMock()
        model.fit = MagicMock()
        pred    = _make_pred_series()
        model.predict = MagicMock(return_value=pred)

        load_mock = MagicMock(return_value=["expr_b"])

        stack = self._base_patches()
        with stack, \
             patch("strategies.factor_injector.load_valid_factors", load_mock), \
             patch("strategies.qlib_strategy._build_dataset",
                   return_value=dataset), \
             patch("strategies.qlib_strategy._patch_pytorch_model_best_param"), \
             patch("strategies.qlib_strategy._fit_with_extra_factors") as mock_fit_extra:

            from strategies.qlib_strategy import _run_with_qlib_or_fallback

            _run_with_qlib_or_fallback(
                "market_adaptive", "市场自适应", "Alpha158",
                lambda: model, ["AAPL", "MSFT"],
                topk=5, progress_cb=None,
            )

        load_mock.assert_called_once()
        mock_fit_extra.assert_called_once()


# ──────────────────────────────────────────────────────────────
#  3. EventBus 新信号
# ──────────────────────────────────────────────────────────────
class TestEventBusSignal(unittest.TestCase):

    def setUp(self):
        from PyQt6.QtWidgets import QApplication
        import sys
        self._app = QApplication.instance() or QApplication(sys.argv)

    def test_rdagent_factors_injected_signal_exists(self):
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        self.assertTrue(hasattr(bus, "rdagent_factors_injected"))

    def test_rdagent_factors_injected_signal_connectable(self):
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        received = []
        bus.rdagent_factors_injected.connect(lambda lst: received.append(lst))
        bus.rdagent_factors_injected.emit(["factor_a", "factor_b"])
        self.assertIn(["factor_a", "factor_b"], received)


if __name__ == "__main__":
    unittest.main(verbosity=2)
