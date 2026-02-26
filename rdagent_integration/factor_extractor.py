"""
因子提取器
解析 RD-Agent 的输出日志/文件，提取结构化因子定义
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class DiscoveredFactor:
    """RD-Agent 发现的因子"""
    name:        str
    expression:  str                    # Qlib 因子表达式（如 Ref(Close,1)/Close-1）
    description: str = ""
    ic_mean:     Optional[float] = None # 因子 IC（若有）
    ic_std:      Optional[float] = None
    sharpe:      Optional[float] = None
    raw_output:  str = ""               # 原始输出行


class FactorExtractor:
    """
    从 RD-Agent 的输出中提取因子定义。

    RD-Agent 输出格式示例（基于 fin_quant 模式）：
      Factor: momentum_5d | Expression: Ref(Close,5)/Close-1 | IC: 0.045 | Sharpe: 1.23
      factor_name: reversal_20d
      expression: 1 - Ref(Close,20)/Close
    """

    # 匹配模式（宽松，适应不同版本 RD-Agent 输出）
    _PATTERNS = [
        # 单行键值格式：Factor: xxx | Expression: yyy | IC: 0.045
        re.compile(
            r"Factor:\s*(?P<name>[\w_]+)"
            r".*?Expression:\s*(?P<expr>[^\|]+)"
            r"(?:.*?IC:\s*(?P<ic>[-\d.]+))?",
            re.IGNORECASE
        ),
        # 多行格式：factor_name: xxx\nexpression: yyy
        re.compile(
            r"factor_name:\s*(?P<name>[\w_]+)",
            re.IGNORECASE
        ),
    ]

    _EXPR_PATTERN = re.compile(r"expression:\s*(?P<expr>[^\n|]+)", re.IGNORECASE)
    _IC_PATTERN   = re.compile(r"\bic(?:_mean)?:\s*(?P<v>[-\d.]+)", re.IGNORECASE)
    _IC_STD_PATTERN = re.compile(r"ic_std:\s*(?P<v>[-\d.]+)", re.IGNORECASE)
    _SHARPE_PATTERN = re.compile(r"sharpe(?:_ratio)?:\s*(?P<v>[-\d.]+)", re.IGNORECASE)

    def extract_from_lines(self, lines: list[str]) -> list[DiscoveredFactor]:
        """
        从日志行列表中提取所有因子。
        采用滑动窗口（连续5行合并后匹配），以处理多行输出。
        """
        factors: list[DiscoveredFactor] = []
        seen_names: set[str] = set()
        window_size = 5

        for i in range(len(lines)):
            window = "\n".join(lines[i : i + window_size])
            factor = self._try_extract(window)
            if factor and factor.name not in seen_names:
                seen_names.add(factor.name)
                factors.append(factor)
                logger.debug(f"提取到因子：{factor.name} | {factor.expression}")

        return factors

    def extract_from_workspace(self, workspace_dir: Path) -> list[DiscoveredFactor]:
        """
        从 RD-Agent 工作目录中读取输出文件并提取因子。
        RD-Agent 通常将因子写入 workspace/factor_*.py 或 output/factors.json
        """
        factors: list[DiscoveredFactor] = []

        # 尝试读取 JSON 输出
        json_paths = list(workspace_dir.glob("**/factors*.json"))
        for p in json_paths:
            try:
                import json
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        f = self._from_dict(item)
                        if f:
                            factors.append(f)
                elif isinstance(data, dict):
                    for name, info in data.items():
                        if isinstance(info, dict):
                            info["name"] = name
                            f = self._from_dict(info)
                            if f:
                                factors.append(f)
            except Exception as e:
                logger.warning(f"解析 {p} 失败：{e}")

        # 尝试读取 Python 因子文件
        py_paths = list(workspace_dir.glob("**/factor_*.py"))
        for p in py_paths:
            try:
                content = p.read_text(encoding="utf-8")
                extracted = self._extract_from_python(p.stem, content)
                if extracted:
                    factors.append(extracted)
            except Exception as e:
                logger.warning(f"解析 {p} 失败：{e}")

        return factors

    def _try_extract(self, text: str) -> Optional[DiscoveredFactor]:
        """尝试从文本块提取一个因子"""
        name = None
        expression = ""

        # 优先使用完整单行格式
        m = self._PATTERNS[0].search(text)
        if m:
            name = m.group("name").strip()
            expression = m.group("expr").strip() if m.group("expr") else ""
            ic_str = m.group("ic") if m.lastgroup and "ic" in m.groupdict() else None
            ic_mean = float(ic_str) if ic_str else None
        else:
            # 多行格式
            m2 = self._PATTERNS[1].search(text)
            if not m2:
                return None
            name = m2.group("name").strip()
            em = self._EXPR_PATTERN.search(text)
            expression = em.group("expr").strip() if em else ""
            ic_mean = None

        if not name:
            return None

        # 提取附加指标
        ic_match = self._IC_PATTERN.search(text)
        if ic_match and ic_mean is None:
            try:
                ic_mean = float(ic_match.group("v"))
            except ValueError:
                pass

        ic_std = None
        std_match = self._IC_STD_PATTERN.search(text)
        if std_match:
            try:
                ic_std = float(std_match.group("v"))
            except ValueError:
                pass

        sharpe = None
        sharpe_match = self._SHARPE_PATTERN.search(text)
        if sharpe_match:
            try:
                sharpe = float(sharpe_match.group("v"))
            except ValueError:
                pass

        return DiscoveredFactor(
            name=name,
            expression=expression or "（未解析）",
            ic_mean=ic_mean,
            ic_std=ic_std,
            sharpe=sharpe,
            raw_output=text[:200],
        )

    def _from_dict(self, d: dict) -> Optional[DiscoveredFactor]:
        name = d.get("name") or d.get("factor_name")
        expr = d.get("expression") or d.get("formula") or d.get("expr", "")
        if not name:
            return None
        return DiscoveredFactor(
            name=str(name),
            expression=str(expr),
            description=str(d.get("description", "")),
            ic_mean=d.get("ic_mean") or d.get("ic"),
            ic_std=d.get("ic_std"),
            sharpe=d.get("sharpe") or d.get("sharpe_ratio"),
        )

    def _extract_from_python(self, stem: str, content: str) -> Optional[DiscoveredFactor]:
        """从 factor_xxx.py 文件提取 Qlib 因子表达式"""
        # 查找 expression = "..." 或 EXPRESSION = "..."
        m = re.search(r'(?:EXPRESSION|expression)\s*=\s*["\']([^"\']+)["\']', content)
        expr = m.group(1) if m else ""
        if not expr:
            return None
        return DiscoveredFactor(
            name=stem,
            expression=expr,
            description=f"从 {stem}.py 提取",
        )
