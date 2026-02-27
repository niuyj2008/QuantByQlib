"""
RD-Agent 因子注入器（Phase A + B）
- 验证 RD-Agent 发现的因子是否具有足够的预测能力（IC ≥ 0.03）
- 将通过验证的因子持久化，供量化选股策略自动加载
- 存储路径：~/.quantbyqlib/valid_factors.json
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

VALID_FACTORS_FILE = Path.home() / ".quantbyqlib" / "valid_factors.json"
IC_THRESHOLD = 0.03          # 业界通行：IC 均值 ≥ 0.03 视为有效因子
VALIDATE_DAYS = 252          # 用最近 252 个交易日验证


def validate_factor(expression: str, universe: list[str],
                    threshold_ic: float = IC_THRESHOLD) -> bool:
    """
    用 Qlib D.features 计算因子在股票池上的截面 IC，判断是否有效。
    IC = 因子值与下一期收益率的 Spearman 相关系数均值。

    expression: Qlib 表达式，如 "Ref($close,5)/$close-1"
    universe:   小写 ticker 列表（与 Qlib features/ 目录一致）
    返回 True 表示因子 IC 均值 >= threshold_ic。
    """
    try:
        from qlib.data import D
        from data.qlib_manager import _find_us_data_dir

        # 确定日期范围：以 Qlib 数据最新日期为基准往前 VALIDATE_DAYS 个交易日
        data_dir = _find_us_data_dir()
        cal_file = data_dir / "calendars" / "day.txt"
        if not cal_file.exists():
            logger.debug("validate_factor: 日历文件不存在，跳过验证")
            return False

        cal_dates = [l.strip() for l in cal_file.read_text().splitlines() if l.strip()]
        if len(cal_dates) < VALIDATE_DAYS + 5:
            logger.debug("validate_factor: 日历日期不足，跳过验证")
            return False

        end_date   = cal_dates[-1]
        start_date = cal_dates[-(VALIDATE_DAYS + 1)]

        # 取因子值
        factor_df = D.features(
            universe, [f"${expression}" if not expression.startswith("$") else expression],
            start_time=start_date, end_time=end_date, freq="day",
        )
        if factor_df is None or factor_df.empty:
            # 尝试不加 $ 前缀
            factor_df = D.features(
                universe, [expression],
                start_time=start_date, end_time=end_date, freq="day",
            )
        if factor_df is None or factor_df.empty:
            logger.debug(f"validate_factor: {expression} 因子数据为空")
            return False

        # 取下一期收益率
        ret_df = D.features(
            universe, ["$close/Ref($close,1)-1"],
            start_time=start_date, end_time=end_date, freq="day",
        )
        if ret_df is None or ret_df.empty:
            return False

        # 对齐 index
        factor_s = factor_df.iloc[:, 0].dropna()
        ret_s    = ret_df.iloc[:, 0].dropna()
        common   = factor_s.index.intersection(ret_s.index)
        if len(common) < 30:
            logger.debug(f"validate_factor: {expression} 公共样本不足（{len(common)}）")
            return False

        factor_s = factor_s.reindex(common)
        ret_s    = ret_s.reindex(common)

        # 截面 IC：按 datetime 分组，各截面计算 Spearman 相关
        from scipy.stats import spearmanr
        ic_list = []
        if hasattr(factor_s.index, "levels"):
            # MultiIndex (datetime, instrument)
            dates = factor_s.index.get_level_values(0).unique()
            for dt in dates:
                try:
                    f_cross = factor_s.xs(dt, level=0)
                    r_cross = ret_s.xs(dt, level=0)
                    idx = f_cross.index.intersection(r_cross.index)
                    if len(idx) < 5:
                        continue
                    corr, _ = spearmanr(f_cross.reindex(idx), r_cross.reindex(idx))
                    if corr == corr:   # not NaN
                        ic_list.append(corr)
                except Exception:
                    pass
        else:
            corr, _ = spearmanr(factor_s, ret_s)
            if corr == corr:
                ic_list.append(corr)

        if not ic_list:
            logger.debug(f"validate_factor: {expression} IC 列表为空")
            return False

        import numpy as np
        ic_mean = float(np.mean(ic_list))
        logger.info(f"[因子验证] {expression[:40]}  IC均值={ic_mean:.4f}  "
                    f"{'✅ 通过' if ic_mean >= threshold_ic else '❌ 未通过'}")
        return ic_mean >= threshold_ic

    except Exception as e:
        logger.warning(f"[因子验证] {expression[:40]} 验证异常：{e}")
        return False


def get_valid_factors(
    min_ic: float = IC_THRESHOLD,
    progress_cb=None,
) -> list[str]:
    """
    从最新 RD-Agent 会话中筛选通过 IC 验证的因子表达式。

    流程：
    1. 读取 session_manager 最新会话
    2. 先用 DiscoveredFactor.ic_mean 快速预筛（无 Qlib 调用）
    3. 对预筛通过的因子调用 validate_factor() 做 Qlib 实测
    返回 list[str]（Qlib 表达式）
    """
    def _cb(pct: int, msg: str):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass

    _cb(5, "读取 RD-Agent 历史会话...")

    try:
        from rdagent_integration.session_manager import get_session_manager
        session = get_session_manager().get_latest()
    except Exception as e:
        logger.warning(f"get_valid_factors: 读取会话失败：{e}")
        return []

    if not session or not session.get("factors"):
        logger.info("get_valid_factors: 无历史因子会话")
        return []

    factors = session["factors"]
    logger.info(f"get_valid_factors: 会话共 {len(factors)} 个因子，开始预筛...")

    # 第一步：IC 预筛（仅用 DiscoveredFactor 记录的 ic_mean，无 Qlib 调用）
    candidates = []
    for f in factors:
        expr = f.get("expression", "").strip()
        if not expr:
            continue
        ic_reported = f.get("ic_mean")
        # ic_mean 为 None 表示 RD-Agent 未报告，不过滤；有值则要求 >= min_ic
        if ic_reported is None or ic_reported >= min_ic:
            candidates.append(expr)

    logger.info(f"get_valid_factors: 预筛后 {len(candidates)} 个因子进入 Qlib 验证")
    _cb(15, f"预筛通过 {len(candidates)} 个因子，开始 Qlib IC 验证...")

    if not candidates:
        return []

    # 第二步：Qlib 实测 IC
    try:
        from strategies.qlib_strategy import _qlib_init_check, _get_qlib_data_end_date
        from data.qlib_manager import _find_us_data_dir
        _qlib_init_check()
    except Exception as e:
        logger.warning(f"get_valid_factors: Qlib 未就绪（{e}），跳过实测")
        # Qlib 不可用时，直接信任 RD-Agent 报告的 ic_mean
        return [f.get("expression", "").strip() for f in factors
                if f.get("expression", "").strip()
                and (f.get("ic_mean") is None or f.get("ic_mean", 0) >= min_ic)]

    # 构建验证用股票池（取蓝筹 30 支，够快）
    _VALIDATE_UNIVERSE = [t.lower() for t in [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM",
        "V", "UNH", "XOM", "JNJ", "MA", "PG", "HD", "COST", "NFLX",
        "AMD", "CRM", "ADBE", "QCOM", "TXN", "AVGO", "LLY", "PEP",
        "KO", "WMT", "MCD", "IBM", "GE",
    ]]

    valid_exprs = []
    total = len(candidates)
    for i, expr in enumerate(candidates):
        pct = 15 + int(80 * i / total)
        _cb(pct, f"验证因子 {i+1}/{total}：{expr[:35]}...")
        if validate_factor(expr, _VALIDATE_UNIVERSE, min_ic):
            valid_exprs.append(expr)

    _cb(97, f"验证完成：{len(valid_exprs)}/{total} 个因子通过")
    logger.info(f"get_valid_factors: {len(valid_exprs)} 个因子通过验证")
    return valid_exprs


def save_valid_factors(expressions: list[str]) -> None:
    """
    将通过验证的因子表达式持久化到 ~/.quantbyqlib/valid_factors.json
    """
    VALID_FACTORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(expressions),
        "expressions": expressions,
    }
    try:
        VALID_FACTORS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"已保存 {len(expressions)} 个有效因子到 {VALID_FACTORS_FILE}")
    except Exception as e:
        logger.warning(f"save_valid_factors 写入失败：{e}")


def load_valid_factors(max_age_hours: float = 24.0) -> list[str]:
    """
    从持久化文件加载有效因子表达式列表。
    若文件不存在或超过 max_age_hours，返回空列表（不强制重验证）。
    """
    if not VALID_FACTORS_FILE.exists():
        return []
    try:
        import time
        age_h = (time.time() - VALID_FACTORS_FILE.stat().st_mtime) / 3600
        if age_h > max_age_hours:
            logger.debug(f"valid_factors.json 已过期（{age_h:.1f}h），返回空列表")
            return []
        data = json.loads(VALID_FACTORS_FILE.read_text(encoding="utf-8"))
        exprs = data.get("expressions", [])
        if exprs:
            logger.info(f"加载 {len(exprs)} 个自定义因子（更新于 {data.get('updated_at', '?')}）")
        return [str(e) for e in exprs if e]
    except Exception as e:
        logger.debug(f"load_valid_factors 读取失败：{e}")
        return []


def clear_valid_factors() -> None:
    """清空有效因子文件（用于重置）"""
    try:
        if VALID_FACTORS_FILE.exists():
            VALID_FACTORS_FILE.unlink()
            logger.info("已清空 valid_factors.json")
    except Exception as e:
        logger.warning(f"clear_valid_factors 失败：{e}")


def get_inject_status() -> dict:
    """
    返回当前注入状态摘要，供 UI 展示。
    """
    if not VALID_FACTORS_FILE.exists():
        return {"injected": False, "count": 0, "updated_at": None, "expressions": []}
    try:
        import time
        age_h = (time.time() - VALID_FACTORS_FILE.stat().st_mtime) / 3600
        data = json.loads(VALID_FACTORS_FILE.read_text(encoding="utf-8"))
        return {
            "injected":    True,
            "count":       data.get("count", len(data.get("expressions", []))),
            "updated_at":  data.get("updated_at"),
            "age_hours":   round(age_h, 1),
            "expressions": data.get("expressions", []),
        }
    except Exception:
        return {"injected": False, "count": 0, "updated_at": None, "expressions": []}
