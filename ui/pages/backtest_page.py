"""
策略回测页面
- 参数配置（策略/日期/初始资金）
- 运行控制 + 进度条
- 结果展示：KPI 徽章 + 净值曲线（pyqtgraph）+ IC 统计
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QDateEdit, QGridLayout,
    QFrame, QProgressBar, QDoubleSpinBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QDate, QThreadPool
from PyQt6.QtGui import QFont

from ui.theme import COLORS

_STRATEGY_OPTIONS = [
    ("deep_learning",       "🧠 深度学习集成"),
    ("intraday_profit",     "⚡ 短线获利"),
    ("growth_stocks",       "🌱 成长股选股"),
    ("market_adaptive",     "🔄 市场自适应"),
    ("pytorch_full_market", "🌐 全市场深度学习"),
]


class _MetricBadge(QFrame):
    def __init__(self, label: str, value: str, sub: str = "", color: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(120)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(12, 10, 12, 10)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        val = QLabel(value)
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        val.setFont(font)
        val.setStyleSheet(f"color:{color or COLORS['text_primary']};")
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(val)

        if sub:
            sl = QLabel(sub)
            sl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:10px;")
            sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(sl)


class BacktestPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_report = None
        self._kpi_widgets: list = []
        self._has_pyqtgraph = False
        self._plot_widget = None
        self._setup_ui()
        self._connect_events()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        title = QLabel("📈 策略回测")
        title.setObjectName("page_title")
        layout.addWidget(title)

        subtitle = QLabel("使用历史数据验证策略有效性（Qlib 已初始化时使用完整回测，否则使用简化模式）")
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(subtitle)

        # ── 参数配置卡片 ──
        param_card = QFrame()
        param_card.setObjectName("card")
        param_layout = QGridLayout(param_card)
        param_layout.setSpacing(12)
        param_layout.setColumnStretch(1, 1)
        param_layout.setColumnStretch(3, 1)

        param_layout.addWidget(self._lbl("策略："), 0, 0)
        self._strategy_combo = QComboBox()
        for key, name in _STRATEGY_OPTIONS:
            self._strategy_combo.addItem(name, key)
        param_layout.addWidget(self._strategy_combo, 0, 1)

        param_layout.addWidget(self._lbl("初始资金："), 0, 2)
        self._capital_spin = QDoubleSpinBox()
        self._capital_spin.setRange(10_000, 100_000_000)
        self._capital_spin.setDecimals(0)
        self._capital_spin.setSingleStep(10_000)
        self._capital_spin.setValue(1_000_000)
        self._capital_spin.setPrefix("$ ")
        param_layout.addWidget(self._capital_spin, 0, 3)

        param_layout.addWidget(self._lbl("开始日期："), 1, 0)
        self._start_date = QDateEdit(QDate(2022, 1, 1))
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        param_layout.addWidget(self._start_date, 1, 1)

        param_layout.addWidget(self._lbl("结束日期："), 1, 2)
        self._end_date = QDateEdit(QDate(2024, 12, 31))
        self._end_date.setCalendarPopup(True)
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        param_layout.addWidget(self._end_date, 1, 3)

        param_layout.addWidget(self._lbl("Top-K 持仓："), 2, 0)
        self._topk_combo = QComboBox()
        for k in [20, 30, 50, 100]:
            self._topk_combo.addItem(f"Top {k}", k)
        self._topk_combo.setCurrentIndex(2)
        param_layout.addWidget(self._topk_combo, 2, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setMinimumHeight(8)
        param_layout.addWidget(self._progress_bar, 3, 0, 1, 4)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        param_layout.addWidget(self._status_label, 4, 0, 1, 3)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("▶ 开始回测")
        self._run_btn.setMinimumHeight(42)
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)
        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.setMinimumHeight(42)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._stop_btn)
        param_layout.addLayout(btn_row, 4, 3)
        layout.addWidget(param_card)

        # ── 结果区域 ──
        self._result_area = QWidget()
        rl = QVBoxLayout(self._result_area)
        rl.setSpacing(12)
        rl.setContentsMargins(0, 0, 0, 0)

        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(12)
        rl.addLayout(self._kpi_row)

        # 净值曲线容器
        self._chart_frame = QFrame()
        self._chart_frame.setObjectName("card")
        self._chart_frame.setMinimumHeight(280)
        cl = QVBoxLayout(self._chart_frame)

        self._chart_title = QLabel("净值曲线")
        self._chart_title.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:12px; font-weight:bold;"
        )
        cl.addWidget(self._chart_title)

        try:
            import pyqtgraph as pg
            self._plot_widget = pg.PlotWidget(background=COLORS["bg_card"])
            self._plot_widget.setLabel("left", "净值")
            self._plot_widget.setLabel("bottom", "交易日（序号）")
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self._plot_widget.addLegend()
            cl.addWidget(self._plot_widget)
            self._has_pyqtgraph = True
        except ImportError:
            no_lbl = QLabel("安装 pyqtgraph 启用图表：pip install pyqtgraph")
            no_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:12px;")
            no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(no_lbl)

        rl.addWidget(self._chart_frame)

        # IC 统计行
        self._ic_frame = QFrame()
        self._ic_frame.setObjectName("card")
        il = QVBoxLayout(self._ic_frame)
        self._ic_label = QLabel("IC 统计：暂无数据")
        self._ic_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        il.addWidget(self._ic_label)
        rl.addWidget(self._ic_frame)

        self._result_area.hide()
        layout.addWidget(self._result_area, stretch=1)

        # 占位
        self._placeholder = QLabel(
            "选择策略和日期范围后点击「开始回测」\n\n"
            "将显示：年化收益 / Sharpe / 最大回撤 / IC / 净值曲线"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:13px; "
            f"border:1px dashed {COLORS['border']}; border-radius:12px; padding:60px;"
        )
        self._placeholder.setWordWrap(True)
        layout.addWidget(self._placeholder, stretch=1)

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.backtest_completed.connect(self._on_completed)
        bus.backtest_failed.connect(self._on_failed)

    def _on_run(self) -> None:
        if self._start_date.date() >= self._end_date.date():
            QMessageBox.warning(self, "参数错误", "结束日期必须晚于开始日期")
            return
        start = self._start_date.date().toString("yyyy-MM-dd")
        end   = self._end_date.date().toString("yyyy-MM-dd")
        strategy_key = self._strategy_combo.currentData()
        topk         = self._topk_combo.currentData()
        capital      = self._capital_spin.value()

        from backtesting.backtest_engine import BacktestConfig
        config = BacktestConfig(
            strategy_key=strategy_key,
            start_date=start, end_date=end,
            topk=topk, init_capital=capital,
        )
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._placeholder.hide()
        self._result_area.hide()

        from workers.backtest_worker import BacktestWorker
        worker = BacktestWorker(config)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_progress(self, pct: int, msg: str) -> None:
        self._progress_bar.setValue(pct)
        self._status_label.setText(msg)

    def _on_completed(self, report) -> None:
        self._current_report = report
        self._reset_controls()
        if not report.available:
            self._status_label.setText(f"⚠️ {report.error}")
            self._placeholder.setText(f"回测数据不可用：{report.error}")
            self._placeholder.show()
            return
        self._render_report(report)

    def _on_failed(self, err: str) -> None:
        self._reset_controls()
        self._status_label.setText(f"❌ 回测失败：{err}")
        self._placeholder.setText(f"回测失败：{err}")
        self._placeholder.show()

    def _reset_controls(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)

    def _render_report(self, report) -> None:
        m = report.metrics

        for w in self._kpi_widgets:
            w.deleteLater()
        self._kpi_widgets.clear()
        while self._kpi_row.count():
            self._kpi_row.takeAt(0)

        def _c(v): return COLORS["success"] if v and v >= 0 else COLORS["danger"] if v and v < 0 else COLORS["text_muted"]
        def _f(v, pct=False, dp=2):
            if v is None: return "--"
            return f"{v*100:+.{dp}f}%" if pct else f"{v:.{dp}f}"

        kpis = [
            ("年化收益",  _f(m.annual_return, pct=True), "Annual Return",  _c(m.annual_return)),
            ("Sharpe",   _f(m.sharpe_ratio,  dp=2),     "风险调整收益",   COLORS["primary"]),
            ("最大回撤",  _f(m.max_drawdown,  pct=True), "Max Drawdown",   _c(m.max_drawdown)),
            ("年化波动",  _f(m.volatility,    pct=True), "Volatility",     COLORS["warning"]),
            ("胜率",      _f(m.win_rate,      pct=True, dp=1), "Win Rate", COLORS["text_primary"]),
            ("Alpha",    _f(m.alpha,          pct=True), "vs S&P500",      _c(m.alpha)),
        ]
        for label, value, sub, color in kpis:
            badge = _MetricBadge(label, value, sub, color)
            self._kpi_row.addWidget(badge)
            self._kpi_widgets.append(badge)
        self._kpi_row.addStretch()

        self._render_chart(report)

        ic_parts = []
        if m.ic_mean  is not None: ic_parts.append(f"IC 均值：{m.ic_mean:.4f}")
        if m.ic_std   is not None: ic_parts.append(f"IC 标准差：{m.ic_std:.4f}")
        if m.icir     is not None: ic_parts.append(f"ICIR：{m.icir:.3f}")
        if not ic_parts:           ic_parts = ["IC：简化模式不可用（需 Qlib 完整回测）"]
        days_str = (f"  |  回测 {m.trading_days} 个交易日 "
                    f"（{m.start_date} → {m.end_date}）") if m.trading_days else ""
        self._ic_label.setText("  |  ".join(ic_parts) + days_str)
        self._result_area.show()

    def _render_chart(self, report) -> None:
        if not self._has_pyqtgraph or self._plot_widget is None:
            return
        import pyqtgraph as pg
        self._plot_widget.clear()

        nav = report.nav_series
        bm  = report.bm_series
        if nav.empty:
            return

        self._plot_widget.plot(
            list(range(len(nav))), nav.values.tolist(),
            pen=pg.mkPen(color=COLORS["primary"], width=2),
            name="策略净值",
        )
        if not bm.empty:
            self._plot_widget.plot(
                list(range(len(bm))), bm.values.tolist(),
                pen=pg.mkPen(color=COLORS["text_muted"], width=1.5,
                             style=Qt.PenStyle.DashLine),
                name=report.config.benchmark,
            )
        strat_name = dict(_STRATEGY_OPTIONS).get(
            report.config.strategy_key, report.config.strategy_key
        )
        self._chart_title.setText(
            f"净值曲线：{strat_name}  "
            f"{report.config.start_date} → {report.config.end_date}"
        )

    def _lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        return lbl
