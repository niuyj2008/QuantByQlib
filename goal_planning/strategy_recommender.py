"""
策略推荐器
注：核心逻辑已整合到 goal_planning/goal_manager.py（GoalManager.recommend_strategy）。
本文件提供向后兼容的导入路径。
"""
from __future__ import annotations

from goal_planning.goal_manager import GoalManager, StrategyRecommendation, get_goal_manager

__all__ = ["StrategyRecommendation", "GoalManager", "get_goal_manager"]
