"""
model_cache 单元测试
覆盖：cache_key / load_scores / save_scores / clear_cache / cache_info
使用临时目录隔离，不污染真实缓存目录。
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────
#  1. cache_key
# ──────────────────────────────────────────────────────────────
class TestCacheKey(unittest.TestCase):

    def setUp(self):
        from strategies.model_cache import cache_key
        self.ck = cache_key

    def test_returns_12_char_hex(self):
        key = self.ck("growth_stocks", ["AAPL", "MSFT"], "2026-02-26")
        self.assertEqual(len(key), 12)
        int(key, 16)   # 应为合法十六进制

    def test_deterministic(self):
        """相同输入产生相同输出"""
        k1 = self.ck("growth_stocks", ["AAPL", "MSFT"], "2026-02-26")
        k2 = self.ck("growth_stocks", ["AAPL", "MSFT"], "2026-02-26")
        self.assertEqual(k1, k2)

    def test_universe_order_independent(self):
        """股票池顺序不同，键应相同（排序后 hash）"""
        k1 = self.ck("s", ["AAPL", "MSFT", "NVDA"], "2026-01-01")
        k2 = self.ck("s", ["NVDA", "AAPL", "MSFT"], "2026-01-01")
        self.assertEqual(k1, k2)

    def test_different_strategy_different_key(self):
        k1 = self.ck("growth_stocks", ["AAPL"], "2026-01-01")
        k2 = self.ck("market_adaptive", ["AAPL"], "2026-01-01")
        self.assertNotEqual(k1, k2)

    def test_different_date_different_key(self):
        k1 = self.ck("s", ["AAPL"], "2026-01-01")
        k2 = self.ck("s", ["AAPL"], "2026-01-02")
        self.assertNotEqual(k1, k2)

    def test_extra_exprs_none_equals_missing(self):
        """extra_exprs=None 和不传应产生相同键（向后兼容）"""
        k1 = self.ck("s", ["AAPL"], "2026-01-01")
        k2 = self.ck("s", ["AAPL"], "2026-01-01", None)
        self.assertEqual(k1, k2)

    def test_extra_exprs_changes_key(self):
        """传入 extra_exprs 时键应与不传不同"""
        k1 = self.ck("s", ["AAPL"], "2026-01-01")
        k2 = self.ck("s", ["AAPL"], "2026-01-01", ["Ref($close,5)/$close-1"])
        self.assertNotEqual(k1, k2)

    def test_extra_exprs_order_independent(self):
        """extra_exprs 顺序不同，键应相同（排序后 hash）"""
        k1 = self.ck("s", ["AAPL"], "2026-01-01", ["expr_a", "expr_b"])
        k2 = self.ck("s", ["AAPL"], "2026-01-01", ["expr_b", "expr_a"])
        self.assertEqual(k1, k2)

    def test_different_extra_exprs_different_key(self):
        k1 = self.ck("s", ["AAPL"], "2026-01-01", ["expr_a"])
        k2 = self.ck("s", ["AAPL"], "2026-01-01", ["expr_b"])
        self.assertNotEqual(k1, k2)

    def test_extra_exprs_empty_list_same_as_none(self):
        """空列表（falsy）应与 None 产生相同键"""
        k1 = self.ck("s", ["AAPL"], "2026-01-01", None)
        k2 = self.ck("s", ["AAPL"], "2026-01-01", [])
        self.assertEqual(k1, k2)


# ──────────────────────────────────────────────────────────────
#  2. save_scores / load_scores / clear_cache / cache_info
# ──────────────────────────────────────────────────────────────
class TestCacheIO(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self._patcher = patch(
            "strategies.model_cache.CACHE_DIR",
            Path(self._tmpdir),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_scores(self) -> pd.Series:
        return pd.Series(
            {"AAPL": 0.92, "MSFT": 0.85, "NVDA": 0.78},
            name="score",
        )

    def test_save_creates_pkl_file(self):
        from strategies.model_cache import save_scores
        save_scores("testkey001", self._make_scores())
        self.assertTrue((Path(self._tmpdir) / "testkey001.pkl").exists())

    def test_load_returns_same_series(self):
        from strategies.model_cache import save_scores, load_scores
        original = self._make_scores()
        save_scores("testkey002", original)
        loaded = load_scores("testkey002", max_age_hours=24.0)
        self.assertIsNotNone(loaded)
        pd.testing.assert_series_equal(loaded, original)

    def test_load_missing_key_returns_none(self):
        from strategies.model_cache import load_scores
        result = load_scores("no_such_key")
        self.assertIsNone(result)

    def test_load_expired_cache_returns_none(self):
        """超过 max_age_hours 的缓存应返回 None"""
        from strategies.model_cache import save_scores, load_scores
        import os

        save_scores("expiredkey", self._make_scores())
        cache_file = Path(self._tmpdir) / "expiredkey.pkl"
        old_time = time.time() - 7200   # 2小时前
        os.utime(cache_file, (old_time, old_time))

        result = load_scores("expiredkey", max_age_hours=1.0)
        self.assertIsNone(result)

    def test_load_unexpired_cache_returns_series(self):
        """未过期的缓存应正常返回"""
        from strategies.model_cache import save_scores, load_scores

        save_scores("freshkey", self._make_scores())
        result = load_scores("freshkey", max_age_hours=24.0)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.Series)

    def test_load_corrupted_cache_returns_none(self):
        """pickle 损坏时应静默返回 None"""
        bad_file = Path(self._tmpdir) / "badkey.pkl"
        bad_file.write_bytes(b"NOT_A_PICKLE")

        from strategies.model_cache import load_scores
        result = load_scores("badkey")
        self.assertIsNone(result)

    def test_load_non_series_returns_none(self):
        """缓存内容不是 pd.Series 时应返回 None"""
        import pickle
        bad_file = Path(self._tmpdir) / "notserieskey.pkl"
        with open(bad_file, "wb") as f:
            pickle.dump({"a": 1}, f)

        from strategies.model_cache import load_scores
        result = load_scores("notserieskey")
        self.assertIsNone(result)

    def test_clear_cache_removes_all_pkl(self):
        from strategies.model_cache import save_scores, clear_cache

        save_scores("k1", self._make_scores())
        save_scores("k2", self._make_scores())
        n = clear_cache()
        self.assertEqual(n, 2)
        remaining = list(Path(self._tmpdir).glob("*.pkl"))
        self.assertEqual(len(remaining), 0)

    def test_clear_cache_empty_dir_returns_zero(self):
        from strategies.model_cache import clear_cache
        n = clear_cache()
        self.assertEqual(n, 0)

    def test_clear_nonexistent_dir_returns_zero(self):
        """CACHE_DIR 不存在时 clear_cache 应返回 0 不抛异常"""
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        from strategies.model_cache import clear_cache
        n = clear_cache()
        self.assertEqual(n, 0)

    def test_cache_info_counts_files(self):
        from strategies.model_cache import save_scores, cache_info

        self.assertEqual(cache_info()["count"], 0)
        save_scores("k1", self._make_scores())
        save_scores("k2", self._make_scores())
        info = cache_info()
        self.assertEqual(info["count"], 2)
        # size_mb 对于小文件可能 round 到 0.0，检查 dir 和 count 即足够
        self.assertIn("dir", info)
        self.assertIn("size_mb", info)

    def test_cache_info_nonexistent_dir(self):
        """CACHE_DIR 不存在时 cache_info 应返回 count=0"""
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        from strategies.model_cache import cache_info
        info = cache_info()
        self.assertEqual(info["count"], 0)

    def test_save_large_series(self):
        """能正常缓存/加载大型 Series（500 支股票）"""
        from strategies.model_cache import save_scores, load_scores

        tickers = [f"TICK{i:04d}" for i in range(500)]
        scores  = pd.Series(np.random.rand(500), index=tickers)
        save_scores("largekey", scores)
        loaded = load_scores("largekey")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
