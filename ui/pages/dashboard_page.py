"""
仪表盘页面
- 持仓总览（总市值、盈亏）——来自 portfolio_manager 真实数据
- 盈利目标进度——来自 goal_manager 真实数据
- 最新交易信号——来自最近一次选股结果
- 个股快速搜索（复用 StockDetailPanel）
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGridLayout, QFrame,
    QScrollArea, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from ui.theme import COLORS


# ── 小组件 ────────────────────────────────────────────────────


class _MetricCard(QFrame):
    """KPI 指标卡片（可更新）"""
    def __init__(self, title: str, value: str = "--", subtitle: str = "",
                 value_color: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px;"
        )
        layout.addWidget(self._title_lbl)

        self._value_lbl = QLabel(value)
        vf = QFont()
        vf.setPointSize(18)
        vf.setBold(True)
        self._value_lbl.setFont(vf)
        self._value_lbl.setStyleSheet(
            f"color:{value_color or COLORS['text_primary']};"
        )
        layout.addWidget(self._value_lbl)

        self._sub_lbl = QLabel(subtitle)
        self._sub_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:10px;"
        )
        layout.addWidget(self._sub_lbl)

    def update(self, value: str, color: str = "", subtitle: str = "") -> None:
        self._value_lbl.setText(value)
        if color:
            self._value_lbl.setStyleSheet(f"color:{color};")
        if subtitle:
            self._sub_lbl.setText(subtitle)


class _SignalRow(QFrame):
    """单条信号行（用于仪表盘快速预览）"""
    _SIGNAL_COLORS = {
        "BUY":        COLORS["success"],
        "STRONG_BUY": COLORS["success"],
        "SELL":       COLORS["danger"],
        "HOLD":       COLORS["warning"],
        "WATCH":      COLORS["info"],
    }

    def __init__(self, sig, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        ticker_lbl = QLabel(sig.ticker)
        f = QFont()
        f.setBold(True)
        ticker_lbl.setFont(f)
        ticker_lbl.setFixedWidth(60)
        layout.addWidget(ticker_lbl)

        color = self._SIGNAL_COLORS.get(sig.signal, COLORS["text_muted"])
        signal_lbl = QLabel(sig.signal_zh)
        signal_lbl.setStyleSheet(f"color:{color}; font-weight:bold; font-size:12px;")
        signal_lbl.setFixedWidth(70)
        layout.addWidget(signal_lbl)

        score_lbl = QLabel(f"{sig.score:.3f}")
        score_lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px;")
        layout.addWidget(score_lbl)
        layout.addStretch()

        if sig.change_pct is not None:
            sign = "+" if sig.change_pct >= 0 else ""
            chg_color = COLORS["success"] if sig.change_pct >= 0 else COLORS["danger"]
            chg_lbl = QLabel(f"{sign}{sig.change_pct:.2f}%")
            chg_lbl.setStyleSheet(f"color:{chg_color}; font-size:11px;")
            layout.addWidget(chg_lbl)


# ── 主页面 ─────────────────────────────────────────────────────


class DashboardPage(QWidget):
    """仪表盘页面"""
    search_requested = pyqtSignal(str)    # 用户搜索个股

    def __init__(self, parent=None):
        super().__init__(parent)
        self._latest_signals: list = []
        self._setup_ui()
        self._connect_events()
        # 启动后延迟加载（等待持仓 DB 就绪）
        QTimer.singleShot(800, self._refresh_portfolio)
        QTimer.singleShot(900, self._refresh_goals)

    # ── UI 构建 ──────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(14)

        # 标题 + 搜索栏
        top_row = QHBoxLayout()
        title = QLabel("📊 仪表盘")
        title.setObjectName("page_title")
        top_row.addWidget(title)
        top_row.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索个股（如 NVDA / AAPL）→ 快速分析")
        self._search_input.setMinimumHeight(36)
        self._search_input.setFixedWidth(300)
        self._search_input.returnPressed.connect(self._on_search)
        top_row.addWidget(self._search_input)

        search_btn = QPushButton("🔍 分析")
        search_btn.setFixedWidth(80)
        search_btn.setMinimumHeight(36)
        search_btn.clicked.connect(self._on_search)
        top_row.addWidget(search_btn)
        layout.addLayout(top_row)

        # ── KPI 卡片行 ──
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)

        self._card_market_value = _MetricCard("总持仓市值", "--", "总投入：--")
        self._card_total_pnl    = _MetricCard("总盈亏", "--", "未实现 + 已实现")
        self._card_today_pnl    = _MetricCard("今日涨跌", "--", "按持仓加权")
        self._card_positions    = _MetricCard("持仓支数", "--", "活跃持仓")
        self._card_goal         = _MetricCard("目标进度", "--", "无活跃目标")

        for card in [
            self._card_market_value, self._card_total_pnl,
            self._card_today_pnl,    self._card_positions,
            self._card_goal,
        ]:
            kpi_row.addWidget(card, stretch=1)

        layout.addLayout(kpi_row)

        # ── 下方双栏：信号 + 持仓 ──
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        bottom.addWidget(self._build_signals_panel(), stretch=1)
        bottom.addWidget(self._build_portfolio_panel(), stretch=1)
        layout.addLayout(bottom, stretch=1)

    def _build_signals_panel(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        vl = QVBoxLayout(card)
        vl.setSpacing(6)

        # 标题行
        hdr = QHBoxLayout()
        lbl = QLabel("⚡ 最新交易信号")
        lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:13px; font-weight:bold;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._signals_time_lbl = QLabel("")
        self._signals_time_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:10px;"
        )
        hdr.addWidget(self._signals_time_lbl)
        vl.addLayout(hdr)

        # 滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._signals_inner = QWidget()
        self._signals_vl = QVBoxLayout(self._signals_inner)
        self._signals_vl.setSpacing(2)
        self._signals_vl.setContentsMargins(0, 0, 0, 0)
        self._signals_vl.addStretch()
        scroll.setWidget(self._signals_inner)
        vl.addWidget(scroll, stretch=1)

        self._signals_empty = QLabel(
            "尚无信号\n\n请先在「量化选股」运行策略"
        )
        self._signals_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._signals_empty.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:12px; padding:20px;"
        )
        vl.addWidget(self._signals_empty)

        return card

    def _build_portfolio_panel(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        vl = QVBoxLayout(card)
        vl.setSpacing(8)

        hdr = QLabel("💼 持仓概况")
        hdr.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:13px; font-weight:bold;"
        )
        vl.addWidget(hdr)

        # 持仓行容器
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._portfolio_inner = QWidget()
        self._portfolio_vl = QVBoxLayout(self._portfolio_inner)
        self._portfolio_vl.setSpacing(4)
        self._portfolio_vl.setContentsMargins(0, 0, 0, 0)
        self._portfolio_vl.addStretch()
        scroll.setWidget(self._portfolio_inner)
        vl.addWidget(scroll, stretch=1)

        self._portfolio_empty = QLabel(
            "暂无持仓\n\n请前往「持仓管理」录入"
        )
        self._portfolio_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._portfolio_empty.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:12px; padding:20px;"
        )
        vl.addWidget(self._portfolio_empty)

        # 目标进度条
        self._goal_frame = QFrame()
        self._goal_frame.setObjectName("card")
        gl = QVBoxLayout(self._goal_frame)
        gl.setSpacing(4)
        gl.setContentsMargins(8, 6, 8, 6)
        self._goal_name_lbl = QLabel("当前目标：--")
        self._goal_name_lbl.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px;"
        )
        gl.addWidget(self._goal_name_lbl)
        self._goal_bar = QProgressBar()
        self._goal_bar.setRange(0, 100)
        self._goal_bar.setValue(0)
        self._goal_bar.setMaximumHeight(8)
        self._goal_bar.setTextVisible(False)
        gl.addWidget(self._goal_bar)
        self._goal_detail_lbl = QLabel("")
        self._goal_detail_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:10px;"
        )
        gl.addWidget(self._goal_detail_lbl)
        self._goal_frame.hide()
        vl.addWidget(self._goal_frame)

        return card

    # ── 事件连接 ─────────────────────────────────────────────

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.portfolio_updated.connect(self._refresh_portfolio)
        bus.screening_completed.connect(self._on_screening_done)

    def _on_search(self) -> None:
        ticker = self._search_input.text().strip().upper()
        if not ticker:
            return
        self.search_requested.emit(ticker)
        try:
            from core.event_bus import get_event_bus
            get_event_bus().show_ticker_detail.emit(ticker, None)
        except Exception:
            pass

    # ── 数据刷新 ─────────────────────────────────────────────

    def _refresh_portfolio(self) -> None:
        """从 portfolio_manager 获取真实持仓数据，刷新 KPI + 持仓列表"""
        try:
            from portfolio.manager import get_portfolio_manager
            pm = get_portfolio_manager()
            summary = pm.get_summary()

            total_value    = summary.get("total_market_value", 0.0)
            total_cost     = summary.get("total_cost", 0.0)
            unrealized_pnl = summary.get("total_unrealized_pnl", 0.0)
            realized_pnl   = summary.get("total_realized_pnl", 0.0)
            total_pnl      = unrealized_pnl + realized_pnl
            positions      = summary.get("positions", [])
            n_pos          = len([p for p in positions if p.get("shares", 0) > 0])

            # 市值卡片
            mv_str = f"${total_value:,.0f}" if total_value else "--"
            cost_str = f"总投入：${total_cost:,.0f}" if total_cost else "总投入：--"
            self._card_market_value.update(mv_str, subtitle=cost_str)

            # 盈亏卡片
            if total_cost > 0:
                pnl_pct   = total_pnl / total_cost * 100
                pnl_color = COLORS["success"] if total_pnl >= 0 else COLORS["danger"]
                sign      = "+" if total_pnl >= 0 else ""
                pnl_str   = f"{sign}${total_pnl:,.0f}"
                self._card_total_pnl.update(
                    pnl_str, color=pnl_color,
                    subtitle=f"{sign}{pnl_pct:.1f}%"
                )
            else:
                self._card_total_pnl.update("--")

            # 今日盈亏（简化：显示未实现 PnL 作为快照）
            if unrealized_pnl != 0 and total_cost > 0:
                upnl_color = COLORS["success"] if unrealized_pnl >= 0 else COLORS["danger"]
                sign = "+" if unrealized_pnl >= 0 else ""
                self._card_today_pnl.update(
                    f"{sign}${unrealized_pnl:,.0f}",
                    color=upnl_color,
                    subtitle="未实现盈亏"
                )

            # 持仓支数
            self._card_positions.update(
                str(n_pos),
                subtitle=f"活跃持仓"
            )

            # 更新持仓列表
            self._populate_portfolio_list(positions)

        except Exception:
            pass   # 持仓 DB 未就绪时静默

    def _refresh_goals(self) -> None:
        """从 goal_manager 获取目标进度"""
        try:
            from goal_planning.goal_manager import get_goal_manager
            gm = get_goal_manager()
            active = gm.get_active_goals()
            if not active:
                self._card_goal.update("--", subtitle="无活跃目标")
                return

            goal = active[0]  # 取第一个活跃目标
            progress = gm.calc_progress(goal)

            pct_str = f"{progress.current_pct * 100:+.1f}%"
            color   = COLORS["success"] if progress.on_track else COLORS["warning"]
            target  = f"目标 {progress.target_pct * 100:.1f}%"
            self._card_goal.update(pct_str, color=color, subtitle=target)

            # 进度条
            bar_val = min(100, int(progress.current_pct / progress.target_pct * 100))
            self._goal_bar.setValue(max(0, bar_val))
            self._goal_name_lbl.setText(f"目标：{goal['name']}")
            days_left = progress.days_remaining
            on_track_txt = "✓ 进度正常" if progress.on_track else "⚠ 进度落后"
            self._goal_detail_lbl.setText(
                f"剩余 {days_left} 天  |  {on_track_txt}"
            )
            self._goal_frame.show()

        except Exception:
            pass

    def _on_screening_done(self, results: list) -> None:
        """选股完成后生成信号并展示"""
        try:
            from signals.signal_generator import SignalGenerator
            signals = SignalGenerator().generate(results)
            self._latest_signals = signals
            self._populate_signals_list(signals)
            if signals:
                self._signals_time_lbl.setText(f"更新：{signals[0].generated_at[11:16]}")
        except Exception:
            pass

    def _populate_signals_list(self, signals: list) -> None:
        """填充信号列表（只显示前 BUY/SELL 信号，最多 10 条）"""
        # 清空旧内容（保留 stretch）
        while self._signals_vl.count() > 1:
            item = self._signals_vl.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        important = [s for s in signals if s.signal in ("BUY", "STRONG_BUY", "SELL")][:10]

        if not important:
            self._signals_empty.show()
            return

        self._signals_empty.hide()
        for sig in important:
            row = _SignalRow(sig)
            self._signals_vl.insertWidget(self._signals_vl.count() - 1, row)

    def _populate_portfolio_list(self, positions: list) -> None:
        """填充持仓列表（简化显示：股票+盈亏%）"""
        while self._portfolio_vl.count() > 1:
            item = self._portfolio_vl.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        active = [p for p in positions if p.get("shares", 0) > 0]
        if not active:
            self._portfolio_empty.show()
            return

        self._portfolio_empty.hide()
        for pos in active[:12]:
            row = self._make_portfolio_row(pos)
            self._portfolio_vl.insertWidget(self._portfolio_vl.count() - 1, row)

    def _make_portfolio_row(self, pos: dict) -> QFrame:
        row = QFrame()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 3, 8, 3)
        hl.setSpacing(10)

        symbol_lbl = QLabel(pos.get("symbol", ""))
        f = QFont()
        f.setBold(True)
        symbol_lbl.setFont(f)
        symbol_lbl.setFixedWidth(60)
        hl.addWidget(symbol_lbl)

        shares_lbl = QLabel(f"{pos.get('shares', 0):.0f} 股")
        shares_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        hl.addWidget(shares_lbl)
        hl.addStretch()

        # 未实现盈亏
        unrealized = pos.get("unrealized_pnl")
        if unrealized is not None:
            color = COLORS["success"] if unrealized >= 0 else COLORS["danger"]
            sign  = "+" if unrealized >= 0 else ""
            pnl_lbl = QLabel(f"{sign}${unrealized:,.0f}")
            pnl_lbl.setStyleSheet(f"color:{color}; font-size:11px;")
            hl.addWidget(pnl_lbl)

            # 百分比
            cost = pos.get("cost_basis")
            if cost and cost > 0:
                pct = unrealized / cost * 100
                pct_lbl = QLabel(f"({sign}{pct:.1f}%)")
                pct_lbl.setStyleSheet(f"color:{color}; font-size:10px;")
                hl.addWidget(pct_lbl)

        return row
