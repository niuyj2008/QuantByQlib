"""
目标进度追踪器
注：核心逻辑已整合到 goal_planning/goal_manager.py（GoalManager.calc_progress）。
本文件提供向后兼容的导入路径。
"""
from __future__ import annotations

from goal_planning.goal_manager import GoalProgress, GoalManager, get_goal_manager

__all__ = ["GoalProgress", "GoalManager", "get_goal_manager"]
