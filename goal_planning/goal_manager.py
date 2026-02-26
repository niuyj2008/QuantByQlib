"""
盈利目标管理器
CRUD 操作 + 进度追踪 + 可行性评估
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from loguru import logger


# ── 策略档案（与计划文档保持一致）────────────────────────────

STRATEGY_PROFILES: dict[str, dict] = {
    "conservative": {
        "label": "稳健型",
        "annual_return_low":  0.06,
        "annual_return_high": 0.12,
        "max_drawdown":       -0.15,
        "recommended_strategies": ["growth_stocks"],
        "position_size_pct":  0.05,
        "stop_loss_pct":      0.08,
        "rebalance":          "月度",
        "max_positions":      20,
        "color":              "success",
    },
    "moderate": {
        "label": "平衡型",
        "annual_return_low":  0.12,
        "annual_return_high": 0.25,
        "max_drawdown":       -0.25,
        "recommended_strategies": ["market_adaptive", "deep_learning"],
        "position_size_pct":  0.08,
        "stop_loss_pct":      0.10,
        "rebalance":          "周度",
        "max_positions":      12,
        "color":              "warning",
    },
    "aggressive": {
        "label": "进取型",
        "annual_return_low":  0.20,
        "annual_return_high": 0.40,
        "max_drawdown":       -0.35,
        "recommended_strategies": ["pytorch_full_market", "intraday_profit"],
        "position_size_pct":  0.10,
        "stop_loss_pct":      0.07,
        "rebalance":          "日度",
        "max_positions":      10,
        "color":              "danger",
    },
}


@dataclass
class GoalProgress:
    """目标进度计算结果"""
    goal_id:          int
    goal_name:        str
    target_pct:       float           # 目标收益率（如 0.15 = 15%）
    current_pct:      float           # 当前实现收益率
    elapsed_days:     int
    total_days:       int
    progress_ratio:   float           # 当前进度 / 目标进度（>1 超前，<1 落后）
    on_track:         bool
    projected_pct:    float           # 按当前速度预计到期收益率
    days_remaining:   int
    status:           str             # "ACTIVE" / "COMPLETED" / "CANCELLED"


@dataclass
class StrategyRecommendation:
    """策略推荐结果"""
    profile_key:        str
    profile_label:      str
    annual_target_pct:  float           # 目标换算年化
    feasible:           bool            # 是否在该风险档位范围内
    warning:            Optional[str]   # 可行性警告
    strategies:         list[str]       # 推荐策略 key 列表
    position_size_pct:  float
    stop_loss_pct:      float
    max_positions:      int
    rebalance:          str
    max_single_buy:     Optional[float] # 1% 风险法则建议单笔金额


class GoalManager:
    """盈利目标管理器"""

    def __init__(self):
        from portfolio.db import get_db
        self._db = get_db()

    # ── CRUD ─────────────────────────────────────────────────

    def create_goal(self, name: str, period_type: str,
                    target_return_pct: float,
                    start_date: str, end_date: str,
                    initial_capital: float) -> int:
        """创建目标，返回 ID"""
        goal_id = self._db.create_goal(
            name=name,
            period_type=period_type,
            target_return_pct=target_return_pct,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
        )
        logger.info(f"创建盈利目标：{name}，目标 {target_return_pct*100:.1f}%")
        return goal_id

    def get_active_goals(self) -> list[dict]:
        return self._db.get_active_goals()

    def get_all_goals(self) -> list[dict]:
        return self._db.get_all_goals()

    def cancel_goal(self, goal_id: int) -> None:
        self._db.update_goal_status(goal_id, "CANCELLED")
        logger.info(f"取消目标 ID={goal_id}")

    def complete_goal(self, goal_id: int) -> None:
        self._db.update_goal_status(goal_id, "COMPLETED")
        logger.info(f"完成目标 ID={goal_id}")

    # ── 进度计算 ──────────────────────────────────────────────

    def calc_progress(self, goal: dict,
                      current_portfolio_value: Optional[float] = None) -> GoalProgress:
        """
        计算目标完成进度
        若传入 current_portfolio_value，用实时市值计算；否则用已实现盈亏估算
        """
        today = date.today()
        start = date.fromisoformat(goal["start_date"])
        end   = date.fromisoformat(goal["end_date"])

        elapsed_days   = max(1, (today - start).days)
        total_days     = max(1, (end - start).days)
        days_remaining = max(0, (end - today).days)

        initial_capital = goal["initial_capital"]
        target_pct      = goal["target_return_pct"]

        # 计算当前收益率
        if current_portfolio_value and initial_capital > 0:
            current_pct = (current_portfolio_value - initial_capital) / initial_capital
        else:
            # 用已实现盈亏 + 未实现盈亏估算
            realized = self._db.get_realized_pnl()
            unrealized = self._get_unrealized_pnl()
            total_gain = realized + unrealized
            current_pct = total_gain / initial_capital if initial_capital > 0 else 0.0

        # 按比例判断是否达标（已过时间 / 总时间 * 目标）
        expected_pct    = target_pct * (elapsed_days / total_days)
        progress_ratio  = (current_pct / expected_pct) if expected_pct > 0 else 1.0
        on_track        = current_pct >= expected_pct * 0.9   # 允许10%误差

        # 预测到期收益率
        daily_rate      = current_pct / elapsed_days if elapsed_days > 0 else 0
        projected_pct   = daily_rate * total_days

        return GoalProgress(
            goal_id=goal["id"],
            goal_name=goal["name"],
            target_pct=target_pct,
            current_pct=current_pct,
            elapsed_days=elapsed_days,
            total_days=total_days,
            progress_ratio=progress_ratio,
            on_track=on_track,
            projected_pct=projected_pct,
            days_remaining=days_remaining,
            status=goal.get("status", "ACTIVE"),
        )

    # ── 策略推荐 ──────────────────────────────────────────────

    def recommend_strategy(self, goal: dict,
                           risk_profile: str = "moderate",
                           current_total_value: Optional[float] = None) -> StrategyRecommendation:
        """
        根据目标和风险偏好推荐策略参数
        检查目标年化是否在风险档位合理范围内
        """
        profile = STRATEGY_PROFILES.get(risk_profile, STRATEGY_PROFILES["moderate"])

        # 将目标收益换算为年化
        start = date.fromisoformat(goal["start_date"])
        end   = date.fromisoformat(goal["end_date"])
        total_days = max(1, (end - start).days)
        annual_target = goal["target_return_pct"] * (365 / total_days)

        # 可行性检查
        low_annual  = profile["annual_return_low"]
        high_annual = profile["annual_return_high"]
        feasible    = low_annual <= annual_target <= high_annual * 1.2   # 宽松20%上限

        warning = None
        if annual_target > high_annual * 1.5:
            warning = (
                f"目标年化 {annual_target*100:.1f}% 超出{profile['label']}预期范围 "
                f"（{low_annual*100:.0f}%-{high_annual*100:.0f}%），"
                f"建议调低目标或切换为进取型"
            )
        elif annual_target > high_annual:
            warning = (
                f"目标年化 {annual_target*100:.1f}% 偏高，"
                f"需要较好的市场环境才能达成"
            )
        elif annual_target < low_annual * 0.5:
            warning = (
                f"目标年化 {annual_target*100:.1f}% 偏低，"
                f"可考虑提高目标或切换稳健型策略以降低风险"
            )

        # 1% 风险法则：单笔最大买入 = 总资产 * 1% / 止损比例
        max_single_buy = None
        if current_total_value and current_total_value > 0:
            max_single_buy = (
                current_total_value * 0.01 / profile["stop_loss_pct"]
            )

        return StrategyRecommendation(
            profile_key=risk_profile,
            profile_label=profile["label"],
            annual_target_pct=annual_target,
            feasible=feasible,
            warning=warning,
            strategies=profile["recommended_strategies"],
            position_size_pct=profile["position_size_pct"],
            stop_loss_pct=profile["stop_loss_pct"],
            max_positions=profile["max_positions"],
            rebalance=profile["rebalance"],
            max_single_buy=max_single_buy,
        )

    # ── 私有方法 ──────────────────────────────────────────────

    def _get_unrealized_pnl(self) -> float:
        """获取当前未实现盈亏（通过持仓管理器）"""
        try:
            from portfolio.manager import get_portfolio_manager
            summary = get_portfolio_manager().get_summary()
            return summary.get("total_unrealized_pnl", 0.0)
        except Exception:
            return 0.0


# 模块级单例
_manager: Optional[GoalManager] = None


def get_goal_manager() -> GoalManager:
    global _manager
    if _manager is None:
        _manager = GoalManager()
    return _manager
