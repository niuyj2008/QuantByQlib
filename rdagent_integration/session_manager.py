"""
RD-Agent 会话管理器
管理多次因子发现会话的历史记录（本地 JSON 存储）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

SESSION_FILE = Path.home() / ".quantbyqlib" / "rdagent_sessions.json"


class SessionManager:
    """
    持久化存储每次因子发现会话的摘要信息。
    """

    def __init__(self):
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._sessions: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if SESSION_FILE.exists():
            try:
                return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self) -> None:
        try:
            SESSION_FILE.write_text(
                json.dumps(self._sessions, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def add_session(self, factors: list, status: str = "completed") -> dict:
        """记录一次因子发现会话"""
        session = {
            "id":           len(self._sessions) + 1,
            "timestamp":    datetime.now().isoformat(timespec="seconds"),
            "status":       status,
            "factor_count": len(factors),
            "factors":      [
                {"name": f.name if hasattr(f, "name") else f.get("name", ""),
                 "expression": f.expression if hasattr(f, "expression") else f.get("expression", "")}
                for f in factors
            ],
        }
        self._sessions.append(session)
        self._save()
        return session

    def get_all(self) -> list[dict]:
        return list(reversed(self._sessions))   # 最新在前

    def get_latest(self) -> Optional[dict]:
        return self._sessions[-1] if self._sessions else None

    def clear(self) -> None:
        self._sessions.clear()
        self._save()


_manager: Optional[SessionManager] = None

def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
