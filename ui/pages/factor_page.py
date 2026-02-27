"""
RD-Agent 因子发现页面
- Docker 状态检测
- 启动/停止控制
- 实时日志流
- 发现因子列表展示
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QProgressBar, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtGui import QColor, QFont

from ui.theme import COLORS


class FactorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._factors: list = []
        self._setup_ui()
        self._connect_events()
        # 延迟检测 Docker 状态（避免阻塞启动）
        QTimer.singleShot(1500, self._check_docker_status)
        # 延迟加载历史会话（若有）
        QTimer.singleShot(800, self._load_latest_session)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        # ── 标题行 ──
        hdr = QHBoxLayout()
        title = QLabel("🤖 因子发现（RD-Agent）")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        hdr.addStretch()
        self._start_btn = QPushButton("▶ 启动因子发现")
        self._start_btn.setMinimumHeight(36)
        self._start_btn.clicked.connect(self._on_start)
        hdr.addWidget(self._start_btn)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.setMinimumHeight(36)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        hdr.addWidget(self._stop_btn)
        layout.addLayout(hdr)

        subtitle = QLabel(
            "使用 RD-Agent + DeepSeek LLM 在 Docker 容器中自动发现量化因子"
        )
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(subtitle)

        # ── 状态卡片 ──
        status_card = QFrame()
        status_card.setObjectName("card")
        sl = QGridLayout(status_card)
        sl.setSpacing(8)

        self._docker_label    = self._info_label("Docker 状态：", "⚪ 检测中...")
        self._container_label = self._info_label("容器状态：",   "--")
        self._iter_label      = self._info_label("运行时长：",   "--")
        self._factor_count_label = self._info_label("已发现因子：", "0 个")

        sl.addWidget(self._docker_label,       0, 0)
        sl.addWidget(self._container_label,    0, 1)
        sl.addWidget(self._iter_label,         1, 0)
        sl.addWidget(self._factor_count_label, 1, 1)

        # 安装说明链接
        hint = QLabel(
            "需要：① Docker Desktop 运行中  "
            "② DeepSeek API Key（参数配置页）  "
            "③ 首次运行需拉取镜像：<code>docker pull msrarambler/rd-agent:latest</code>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        hint.setWordWrap(True)
        sl.addWidget(hint, 2, 0, 1, 2)

        layout.addWidget(status_card)

        # ── 主体：日志 + 因子列表（分屏）──
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

        # 左侧：实时日志
        log_frame = QFrame()
        log_frame.setObjectName("card")
        lf_layout = QVBoxLayout(log_frame)
        lf_layout.setSpacing(6)
        lf_layout.setContentsMargins(0, 8, 0, 0)

        log_header = QLabel("运行日志")
        log_header.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:12px; "
            f"font-weight:bold; padding-left:12px;"
        )
        lf_layout.addWidget(log_header)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText(
            "RD-Agent 日志将实时显示在这里...\n\n"
            "启动前请确认：\n"
            "  1. Docker Desktop 已安装并运行\n"
            "  2. DeepSeek API Key 已在「参数配置」页填写\n"
            "  3. 已拉取镜像（首次约 2GB）\n"
            "     docker pull msrarambler/rd-agent:latest"
        )
        self._log_view.setStyleSheet(
            "background: #0A0718; "
            "color: #A0E8A0; "
            "font-family: 'Courier New', 'Menlo', monospace; "
            "font-size: 11px; "
            f"border: none; "
            "padding: 8px;"
        )
        lf_layout.addWidget(self._log_view)
        splitter.addWidget(log_frame)

        # 右侧：发现因子列表
        factor_frame = QFrame()
        factor_frame.setObjectName("card")
        ff_layout = QVBoxLayout(factor_frame)
        ff_layout.setSpacing(6)
        ff_layout.setContentsMargins(0, 8, 0, 0)

        fhdr = QHBoxLayout()
        fl = QLabel("已发现因子")
        fl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:12px; "
            f"font-weight:bold; padding-left:12px;"
        )
        fhdr.addWidget(fl)
        fhdr.addStretch()
        self._export_factors_btn = QPushButton("📥 导出")
        self._export_factors_btn.setObjectName("btn_secondary")
        self._export_factors_btn.setEnabled(False)
        self._export_factors_btn.clicked.connect(self._on_export_factors)
        fhdr.addWidget(self._export_factors_btn)
        ff_layout.addLayout(fhdr)

        self._factor_table = QTableWidget()
        self._factor_table.setColumnCount(4)
        self._factor_table.setHorizontalHeaderLabels(["因子名", "表达式", "IC均值", "Sharpe"])
        self._factor_table.setAlternatingRowColors(True)
        self._factor_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._factor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._factor_table.verticalHeader().setVisible(False)
        hdr_view = self._factor_table.horizontalHeader()
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self._factor_empty = QLabel("尚未发现因子\n\n启动因子发现后结果将显示在此处")
        self._factor_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._factor_empty.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:12px; padding:20px;"
        )

        ff_layout.addWidget(self._factor_table)
        ff_layout.addWidget(self._factor_empty)
        self._factor_table.hide()

        # ── 注入选股策略区域 ──
        inject_sep = QFrame()
        inject_sep.setFrameShape(QFrame.Shape.HLine)
        inject_sep.setStyleSheet(f"color:{COLORS['border']};")
        ff_layout.addWidget(inject_sep)

        inject_row = QHBoxLayout()
        self._inject_btn = QPushButton("✅ 注入选股策略")
        self._inject_btn.setMinimumHeight(32)
        self._inject_btn.setEnabled(False)
        self._inject_btn.setToolTip(
            "对 RD-Agent 发现的因子进行 IC 验证（IC ≥ 0.03），\n"
            "将通过验证的因子注入 LightGBM 选股策略，并清除旧缓存"
        )
        self._inject_btn.clicked.connect(self._on_inject)
        inject_row.addWidget(self._inject_btn)
        ff_layout.addLayout(inject_row)

        # 注入进度条（验证期间显示）
        self._inject_progress = QProgressBar()
        self._inject_progress.setRange(0, 100)
        self._inject_progress.setTextVisible(True)
        self._inject_progress.setFixedHeight(18)
        self._inject_progress.hide()
        ff_layout.addWidget(self._inject_progress)

        # 注入状态标签（显示"已注入 N 个"或错误）
        self._inject_status_lbl = QLabel("")
        self._inject_status_lbl.setWordWrap(True)
        self._inject_status_lbl.setStyleSheet("font-size:11px; padding: 2px 4px;")
        ff_layout.addWidget(self._inject_status_lbl)

        # ── 已注入因子清单（带 tooltip 通俗描述）──
        injected_hdr = QLabel("已注入因子库：")
        injected_hdr.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px; padding: 2px 0 0 0;"
        )
        ff_layout.addWidget(injected_hdr)

        # 滚动区容纳因子标签列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(120)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._injected_tags_widget = QWidget()
        self._injected_tags_widget.setStyleSheet("background: transparent;")
        self._injected_tags_layout = QVBoxLayout(self._injected_tags_widget)
        self._injected_tags_layout.setSpacing(2)
        self._injected_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._injected_tags_layout.addStretch()

        scroll.setWidget(self._injected_tags_widget)
        ff_layout.addWidget(scroll)

        # 初始化时读取已有注入状态
        QTimer.singleShot(500, self._refresh_inject_status)

        splitter.addWidget(factor_frame)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, stretch=1)

    def _info_label(self, prefix: str, value: str) -> QLabel:
        lbl = QLabel(f"{prefix}<b>{value}</b>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        return lbl

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.rdagent_started.connect(self._on_rdagent_started)
        bus.rdagent_log.connect(self._append_log)
        bus.rdagent_completed.connect(self._on_completed)
        bus.rdagent_failed.connect(self._on_failed)
        bus.rdagent_stopped.connect(self._on_stopped)

    def _check_docker_status(self) -> None:
        """非阻塞 Docker 状态检测"""
        try:
            from rdagent_integration.docker_manager import get_docker_manager
            mgr = get_docker_manager()
            ok, msg = mgr.check_docker()
            color = COLORS["success"] if ok else COLORS["danger"]
            icon  = "🟢" if ok else "🔴"
            self._docker_label.setText(
                f"Docker 状态：<b style='color:{color};'>{icon} {msg}</b>"
            )
            if ok:
                # 检查容器状态
                status = mgr.container_status()
                status_map = {
                    "not_found": "未创建",
                    "running":   "🟢 运行中",
                    "exited":    "⚫ 已退出",
                    "paused":    "🟡 已暂停",
                }
                self._container_label.setText(
                    f"容器状态：<b>{status_map.get(status, status)}</b>"
                )
        except Exception as e:
            self._docker_label.setText(f"Docker 状态：<b style='color:{COLORS['danger']};'>❌ 错误 {e}</b>")

    def _load_latest_session(self) -> None:
        """启动时加载最近一次历史会话（若有），无需 Docker"""
        try:
            from rdagent_integration.session_manager import get_session_manager
            latest = get_session_manager().get_latest()
            if latest and latest.get("factors"):
                factors = latest["factors"]
                self._on_completed(factors)
                self._append_log(
                    f"[INFO] 已加载历史会话 {latest.get('session_id','')}"
                    f"，共 {len(factors)} 个因子"
                )
        except Exception:
            pass  # 历史会话不存在或解析失败时静默忽略

    # ── 控制事件 ──────────────────────────────────────────────

    def _on_start(self) -> None:
        """启动 RD-Agent Worker"""
        from workers.rdagent_worker import RDAgentWorker
        self._worker = RDAgentWorker()
        self._worker.signals.log.connect(self._append_log)
        self._worker.signals.completed.connect(self._on_completed)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.stopped.connect(self._on_stopped)

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._append_log("[INFO] 正在启动 RD-Agent 因子发现...")

        # 刷新 Docker 状态
        self._check_docker_status()

        QThreadPool.globalInstance().start(self._worker)

    def _on_stop(self) -> None:
        """停止 RD-Agent"""
        if self._worker:
            self._worker.cancel()
        self._stop_btn.setEnabled(False)
        self._append_log("[INFO] 正在停止...")

    def _on_rdagent_started(self) -> None:
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        # 启动计时器更新运行时长
        self._start_time = __import__("time").time()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_elapsed)
        self._timer.start(5000)  # 每5秒更新
        self._check_docker_status()

    def _update_elapsed(self) -> None:
        elapsed = int(__import__("time").time() - self._start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        self._iter_label.setText(f"运行时长：<b>{h:02d}:{m:02d}:{s:02d}</b>")

    # ── 日志 + 结果 ──────────────────────────────────────────

    def _append_log(self, text: str) -> None:
        # 按日志级别着色
        color = None
        if "[ERROR]" in text or "error" in text.lower():
            color = COLORS["danger"]
        elif "[WARN]" in text:
            color = COLORS["warning"]
        elif "[INFO]" in text:
            color = COLORS["info"]

        if color:
            self._log_view.append(
                f"<span style='color:{color};'>{self._html_escape(text)}</span>"
            )
        else:
            self._log_view.append(self._html_escape(text))

        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _html_escape(text: str) -> str:
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))

    def _on_completed(self, factors: list) -> None:
        self._reset_controls()
        self._factors = factors
        self._factor_count_label.setText(f"已发现因子：<b>{len(factors)} 个</b>")
        self._append_log(f"[INFO] ✅ 因子发现完成，共 {len(factors)} 个")
        self._populate_factor_table(factors)
        self._export_factors_btn.setEnabled(bool(factors))
        self._inject_btn.setEnabled(bool(factors))
        self._check_docker_status()

    def _on_failed(self, err: str) -> None:
        self._reset_controls()
        self._append_log(f"[ERROR] ❌ 运行失败：{err}")
        self._check_docker_status()

    def _on_stopped(self) -> None:
        self._reset_controls()
        self._append_log("[INFO] ⏹ 已停止")
        self._check_docker_status()

    def _reset_controls(self) -> None:
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        if hasattr(self, "_timer"):
            self._timer.stop()

    def _populate_factor_table(self, factors: list) -> None:
        """将因子填入表格"""
        self._factor_table.setRowCount(0)
        if not factors:
            self._factor_empty.show()
            self._factor_table.hide()
            return

        self._factor_empty.hide()
        self._factor_table.show()

        for item in factors:
            # 支持 DiscoveredFactor dataclass 和 dict
            if hasattr(item, "name"):
                name   = item.name
                expr   = item.expression
                ic     = item.ic_mean
                sharpe = item.sharpe
            else:
                name   = item.get("name", item.get("raw", "")[:30])
                expr   = item.get("expression", "")
                ic     = item.get("ic_mean")
                sharpe = item.get("sharpe")

            row = self._factor_table.rowCount()
            self._factor_table.insertRow(row)

            name_item = QTableWidgetItem(name)
            bold = QFont()
            bold.setBold(True)
            name_item.setFont(bold)
            self._factor_table.setItem(row, 0, name_item)

            expr_item = QTableWidgetItem(expr)
            expr_item.setForeground(QColor(COLORS["text_secondary"]))
            self._factor_table.setItem(row, 1, expr_item)

            ic_item = QTableWidgetItem(f"{ic:.4f}" if ic is not None else "--")
            ic_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if ic is not None:
                ic_item.setForeground(QColor(
                    COLORS["success"] if ic > 0.03 else
                    COLORS["danger"]  if ic < -0.01 else
                    COLORS["text_muted"]
                ))
            self._factor_table.setItem(row, 2, ic_item)

            sharpe_item = QTableWidgetItem(f"{sharpe:.2f}" if sharpe is not None else "--")
            sharpe_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._factor_table.setItem(row, 3, sharpe_item)

    # ── 因子注入 ──────────────────────────────────────────────

    def _on_inject(self) -> None:
        """启动 FactorInjectWorker，后台执行 IC 验证 + 持久化"""
        from workers.factor_inject_worker import FactorInjectWorker
        self._inject_worker = FactorInjectWorker(min_ic=0.03)
        self._inject_worker.signals.progress.connect(self._on_inject_progress)
        self._inject_worker.signals.completed.connect(self._on_inject_completed)
        self._inject_worker.signals.error.connect(self._on_inject_error)

        self._inject_btn.setEnabled(False)
        self._inject_btn.setText("⏳ 验证中...")
        self._inject_progress.setValue(0)
        self._inject_progress.show()
        self._inject_status_lbl.setText("")

        QThreadPool.globalInstance().start(self._inject_worker)

    def _on_inject_progress(self, pct: int, msg: str) -> None:
        self._inject_progress.setValue(pct)
        self._inject_progress.setFormat(f"{msg[:50]}  {pct}%")

    def _on_inject_completed(self, valid_factors: list) -> None:
        self._inject_progress.hide()
        self._inject_btn.setEnabled(True)
        self._inject_btn.setText("✅ 注入选股策略")

        n = len(valid_factors)
        if n > 0:
            color_ok = COLORS["success"]
            self._inject_status_lbl.setText(
                f"<span style='color:{color_ok};'>"
                f"&#x2705; 已注入 {n} 个因子，下次选股将自动使用</span>"
            )
            self._build_factor_tags(valid_factors)
        else:
            color_warn = COLORS["warning"]
            self._inject_status_lbl.setText(
                f"<span style='color:{color_warn};'>"
                f"&#x26A0; 无因子通过 IC 验证（阈值 0.03），策略保持不变</span>"
            )
            self._build_factor_tags([])

    def _on_inject_error(self, err: str) -> None:
        self._inject_progress.hide()
        self._inject_btn.setEnabled(True)
        self._inject_btn.setText("✅ 注入选股策略")
        color_err = COLORS["danger"]
        self._inject_status_lbl.setText(
            f"<span style='color:{color_err};'>&#x274C; 注入失败：{err[:80]}</span>"
        )

    def _build_factor_tags(self, factors: list) -> None:
        """
        在 _injected_tags_layout 中为每个因子创建一个带 tooltip 的标签行。
        factors: list[dict]  含 expression / name / description
        """
        # 清除旧标签（保留末尾的 stretch）
        while self._injected_tags_layout.count() > 1:
            item = self._injected_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not factors:
            empty = QLabel("暂无已注入因子")
            empty.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            self._injected_tags_layout.insertWidget(0, empty)
            return

        for i, f in enumerate(factors):
            expr = f.get("expression", "") if isinstance(f, dict) else str(f)
            name = f.get("name", "")        if isinstance(f, dict) else ""
            desc = f.get("description", "") if isinstance(f, dict) else ""

            display = f"• {name}：{expr[:40]}{'…' if len(expr) > 40 else ''}" if name \
                      else f"• {expr[:50]}{'…' if len(expr) > 50 else ''}"

            lbl = QLabel(display)
            lbl.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:11px; "
                f"padding: 1px 4px; border-radius:3px;"
            )
            lbl.setCursor(Qt.CursorShape.WhatsThisCursor)

            # Tooltip：通俗描述 + 完整表达式
            tooltip_lines = []
            if name:
                tooltip_lines.append(f"<b>{name}</b>")
            if desc:
                tooltip_lines.append(desc)
            tooltip_lines.append(f"<code>{expr}</code>")
            lbl.setToolTip("<br>".join(tooltip_lines))
            lbl.setTextFormat(Qt.TextFormat.PlainText)

            self._injected_tags_layout.insertWidget(i, lbl)

    def _refresh_inject_status(self) -> None:
        """页面加载时读取已有注入状态并展示"""
        try:
            from strategies.factor_injector import get_inject_status
            status = get_inject_status()
            if status.get("injected") and status.get("count", 0) > 0:
                n     = status["count"]
                ts    = status.get("updated_at", "")[:16]
                age_h = status.get("age_hours", 0)
                age_str = f"{age_h:.1f}h 前" if age_h < 48 else f"{int(age_h/24)}天前"
                color_muted = COLORS["text_muted"]
                self._inject_status_lbl.setText(
                    f"<span style='color:{color_muted};'>"
                    f"上次注入（{ts}，{age_str}），共 {n} 个因子</span>"
                )
                self._build_factor_tags(status.get("factors", []))
            else:
                self._build_factor_tags([])
        except Exception:
            pass

    def _on_export_factors(self) -> None:
        """导出因子到 CSV"""
        if not self._factors:
            return
        from PyQt6.QtWidgets import QFileDialog
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "导出因子", "discovered_factors.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["因子名", "表达式", "IC均值", "IC标准差", "Sharpe"])
            for item in self._factors:
                if hasattr(item, "name"):
                    writer.writerow([
                        item.name, item.expression,
                        f"{item.ic_mean:.4f}" if item.ic_mean is not None else "",
                        f"{item.ic_std:.4f}"  if item.ic_std  is not None else "",
                        f"{item.sharpe:.2f}"  if item.sharpe  is not None else "",
                    ])
                else:
                    writer.writerow([
                        item.get("name", ""),
                        item.get("expression", ""),
                        "", "", "",
                    ])
