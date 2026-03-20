"""
F5：数据生成清单（Manifest）
每次 Qlib 运行完成后自动写入 美股交易日记/qlib_manifest.json

Schema:
{
  "last_run": "2026-03-18T16:30:00",
  "run_type": "daily" | "weekly" | "monthly",
  "tickers_processed": [...],
  "generated_files": {
    "charts":   {"status": "success"|"failed"|"skipped", ...},
    "signals":  {"status": ..., "files": [...]},
    "regime":   {"status": "skipped"|"success", "last_available": "..."},
    "backtest": {"status": "skipped"|"success", "last_available": "..."}
  },
  "errors":   [...],
  "warnings": [...]
}
"""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path
from typing import Literal, Optional

from loguru import logger


RunType = Literal["daily", "weekly", "monthly"]


class ManifestBuilder:
    """
    增量构建 Manifest，最终调用 write() 写入文件。

    用法：
        mb = ManifestBuilder("daily", tickers=["AAPL", "MSFT"])
        mb.set_charts(status="success", files=[...])
        mb.set_signals(status="success", files=[...])
        mb.add_warning("PLTR 数据延迟")
        mb.write()
    """

    def __init__(self, run_type: RunType = "daily",
                 tickers: Optional[list[str]] = None):
        self.run_type = run_type
        self.tickers  = tickers or []
        self._charts:   dict = {"status": "skipped"}
        self._signals:  dict = {"status": "skipped"}
        self._regime:   dict = {"status": "skipped"}
        self._backtest: dict = {"status": "skipped"}
        self._errors:   list[str] = []
        self._warnings: list[str] = []
        self._run_time: datetime = datetime.now()

    # ── 各功能状态设置 ────────────────────────────────────────────────────

    def set_charts(self, status: str, files: Optional[list[str]] = None,
                   count: Optional[int] = None, reason: str = "") -> None:
        d: dict = {"status": status, "date": date.today().isoformat()}
        if files is not None:
            d["files"] = files
            d["count"] = count if count is not None else len(files)
        if reason:
            d["reason"] = reason
        self._charts = d

    def set_signals(self, status: str, files: Optional[list[str]] = None,
                    reason: str = "") -> None:
        d: dict = {"status": status, "date": date.today().isoformat()}
        if files is not None:
            d["files"] = files
        if reason:
            d["reason"] = reason
        self._signals = d

    def set_regime(self, status: str, last_available: Optional[str] = None,
                   reason: str = "") -> None:
        d: dict = {"status": status}
        if last_available:
            d["last_available"] = last_available
        if reason:
            d["reason"] = reason
        self._regime = d

    def set_backtest(self, status: str, last_available: Optional[str] = None,
                     reason: str = "") -> None:
        d: dict = {"status": status}
        if last_available:
            d["last_available"] = last_available
        if reason:
            d["reason"] = reason
        self._backtest = d

    def add_error(self, msg: str) -> None:
        self._errors.append(msg)
        logger.error(f"[Manifest] ERROR: {msg}")

    def add_warning(self, msg: str) -> None:
        self._warnings.append(msg)
        logger.warning(f"[Manifest] WARN: {msg}")

    # ── 写入 ──────────────────────────────────────────────────────────────

    def build(self) -> dict:
        return {
            "last_run":           self._run_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "run_type":           self.run_type,
            "tickers_processed":  self.tickers,
            "generated_files": {
                "charts":   self._charts,
                "signals":  self._signals,
                "regime":   self._regime,
                "backtest": self._backtest,
            },
            "errors":   self._errors,
            "warnings": self._warnings,
        }

    def write(self, path: Optional[Path] = None) -> Path:
        from services.output_paths import get_manifest_path
        target = path or get_manifest_path()
        payload = self.build()
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[Manifest] 写入 → {target}")
        return target


# ── 便捷读取函数（供 Claude Skill 使用）────────────────────────────────────

def read_manifest(path: Optional[Path] = None) -> Optional[dict]:
    """读取最新 manifest；文件不存在时返回 None"""
    from services.output_paths import get_manifest_path
    target = path or get_manifest_path()
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[Manifest] 读取失败：{e}")
        return None


def find_last_available(section: str) -> Optional[str]:
    """
    读取 manifest，返回某 section（如 "regime"）的 last_available 日期字符串。
    若 section status=success 且 date 存在，直接返回 date；
    否则返回 last_available（如果有）。
    """
    m = read_manifest()
    if not m:
        return None
    s = m.get("generated_files", {}).get(section, {})
    if s.get("status") == "success":
        return s.get("date") or s.get("last_available")
    return s.get("last_available")
