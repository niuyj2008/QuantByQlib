"""
风险偏好评估
注：风险档位定义已整合到 goal_planning/goal_manager.py（STRATEGY_PROFILES）。
本文件提供向后兼容的导入路径。
"""
from __future__ import annotations

from goal_planning.goal_manager import STRATEGY_PROFILES, get_goal_manager

__all__ = ["STRATEGY_PROFILES", "get_goal_manager"]
