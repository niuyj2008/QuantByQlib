"""
盈利目标页面
- 目标列表 + 进度条
- 新建目标对话框
- 风险偏好选择 → 策略推荐
- 可行性警告
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QComboBox,
    QProgressBar, QDialog, QLineEdit, QDoubleSpinBox,
    QDateEdit, QMessageBox, QFormLayout, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QDate, QTimer
from PyQt6.QtGui import QFont

from ui.theme import COLORS


class _GoalCard(QFrame):
    """单个目标卡片"""

    def __init__(self, goal: dict, progress, recommendation, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._goal = goal
        self._prog = progress
        self._rec  = recommendation
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 标题行 ──
        title_row = QHBoxLayout()

        name_lbl = QLabel(self._goal["name"])
        bold = QFont()
        bold.setPointSize(13)
        bold.setBold(True)
        name_lbl.setFont(bold)
        name_lbl.setStyleSheet(f"color:{COLORS['text_primary']};")
        title_row.addWidget(name_lbl, 1)

        period_text = {
            "MONTHLY":   "月度",
            "QUARTERLY": "季度",
            "YEARLY":    "年度",
        }.get(self._goal.get("period_type", ""), "自定义")
        period_badge = QLabel(period_text)
        period_badge.setStyleSheet(
            f"background:{COLORS['primary']}33; color:{COLORS['primary']}; "
            f"border:1px solid {COLORS['primary']}; border-radius:4px; "
            f"padding:2px 8px; font-size:11px;"
        )
        title_row.addWidget(period_badge)

        # 状态徽章
        status = self._goal.get("status", "ACTIVE")
        status_colors = {
            "ACTIVE":    (COLORS["success"], "进行中"),
            "COMPLETED": (COLORS["primary"], "已完成"),
            "CANCELLED": (COLORS["text_muted"], "已取消"),
        }
        sc, sl = status_colors.get(status, (COLORS["text_muted"], status))
        status_badge = QLabel(sl)
        status_badge.setStyleSheet(
            f"background:{sc}22; color:{sc}; border:1px solid {sc}; "
            f"border-radius:4px; padding:2px 8px; font-size:11px;"
        )
        title_row.addWidget(status_badge)
        layout.addLayout(title_row)

        # ── 日期 + 资金行 ──
        meta_lbl = QLabel(
            f"{self._goal['start_date']} → {self._goal['end_date']}   "
            f"初始资金：${self._goal['initial_capital']:,.0f}   "
            f"目标：+{self._goal['target_return_pct']*100:.1f}%"
        )
        meta_lbl.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        layout.addWidget(meta_lbl)

        # ── 进度条 ──
        if self._prog:
            prog = self._prog
            target_pct  = prog.target_pct
            current_pct = prog.current_pct
            bar_val = int(min(100, max(0, current_pct / target_pct * 100))) if target_pct > 0 else 0

            bar_row = QHBoxLayout()
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(bar_val)
            bar.setMinimumHeight(12)
            bar.setTextVisible(False)
            bar_color = COLORS["success"] if prog.on_track else COLORS["danger"]
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background:{COLORS['bg_card']};
                    border-radius:6px;
                    border:none;
                }}
                QProgressBar::chunk {{
                    background:{bar_color};
                    border-radius:6px;
                }}
            """)
            bar_row.addWidget(bar, 1)

            pct_lbl = QLabel(
                f"当前 {current_pct*100:+.2f}% / 目标 {target_pct*100:.1f}%"
            )
            pct_lbl.setStyleSheet(f"color:{bar_color}; font-size:12px; font-weight:bold;")
            pct_lbl.setFixedWidth(200)
            bar_row.addWidget(pct_lbl)
            layout.addLayout(bar_row)

            # 预测行
            track_icon = "✅" if prog.on_track else "⚠️"
            proj_lbl = QLabel(
                f"{track_icon} 按当前速度预计到期：{prog.projected_pct*100:+.1f}%   "
                f"剩余 {prog.days_remaining} 天（已过 {prog.elapsed_days} 天）"
            )
            proj_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            layout.addWidget(proj_lbl)

        # ── 策略推荐 ──
        if self._rec:
            rec = self._rec
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color:{COLORS['border']};")
            layout.addWidget(sep)

            rec_title = QLabel(f"推荐策略（{rec.profile_label}）：")
            rec_title.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:12px; font-weight:bold;"
            )
            layout.addWidget(rec_title)

            strat_names = {
                "growth_stocks":       "成长股选股（LightGBM）",
                "market_adaptive":     "市场自适应（HMM+LGB）",
                "deep_learning":       "深度学习集成（LSTM）",
                "intraday_profit":     "短线获利（GRU）",
                "pytorch_full_market": "全市场深度学习（MLP）",
            }
            strats_str = " + ".join(strat_names.get(s, s) for s in rec.strategies)
            strat_lbl = QLabel(f"  • {strats_str}")
            strat_lbl.setStyleSheet(f"color:{COLORS['primary_light']}; font-size:12px;")
            layout.addWidget(strat_lbl)

            params_lbl = QLabel(
                f"  • 单股仓位 ≤ {rec.position_size_pct*100:.0f}%   "
                f"止损 {rec.stop_loss_pct*100:.0f}%   "
                f"最多 {rec.max_positions} 支   "
                f"再平衡：{rec.rebalance}"
            )
            params_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            layout.addWidget(params_lbl)

            if rec.max_single_buy:
                buy_lbl = QLabel(
                    f"  ⚠️ 1% 风险法则：单笔最大买入 ${rec.max_single_buy:,.0f}"
                )
                buy_lbl.setStyleSheet(f"color:{COLORS['warning']}; font-size:11px;")
                layout.addWidget(buy_lbl)

            if rec.warning:
                warn_lbl = QLabel(f"  ⚠️ {rec.warning}")
                warn_lbl.setStyleSheet(f"color:{COLORS['danger']}; font-size:11px;")
                warn_lbl.setWordWrap(True)
                layout.addWidget(warn_lbl)


class NewGoalDialog(QDialog):
    """新建目标对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建盈利目标")
        self.setModal(True)
        self.setMinimumWidth(440)
        self._result: Optional[dict] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title_lbl = QLabel("🎯 新建盈利目标")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title_lbl.setFont(font)
        title_lbl.setStyleSheet(f"color:{COLORS['primary']};")
        layout.addWidget(title_lbl)

        form = QFormLayout()
        form.setSpacing(10)

        # 目标名称
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("例：2025 Q1 成长目标")
        self._name_input.setMinimumHeight(34)
        form.addRow("目标名称 *", self._name_input)

        # 周期类型
        self._period_combo = QComboBox()
        self._period_combo.addItems(["月度 (MONTHLY)", "季度 (QUARTERLY)", "年度 (YEARLY)"])
        self._period_combo.setCurrentIndex(1)
        form.addRow("周期类型", self._period_combo)

        # 目标收益率
        self._target_spin = QDoubleSpinBox()
        self._target_spin.setRange(0.1, 500.0)
        self._target_spin.setDecimals(1)
        self._target_spin.setValue(15.0)
        self._target_spin.setSuffix(" %")
        self._target_spin.setMinimumHeight(34)
        form.addRow("目标收益率 *", self._target_spin)

        # 开始日期
        self._start_date = QDateEdit(QDate.currentDate())
        self._start_date.setCalendarPopup(True)
        self._start_date.setDisplayFormat("yyyy-MM-dd")
        self._start_date.setMinimumHeight(34)
        form.addRow("开始日期 *", self._start_date)

        # 结束日期（默认3个月后）
        self._end_date = QDateEdit(QDate.currentDate().addMonths(3))
        self._end_date.setCalendarPopup(True)
        self._end_date.setDisplayFormat("yyyy-MM-dd")
        self._end_date.setMinimumHeight(34)
        form.addRow("结束日期 *", self._end_date)

        # 初始资金
        self._capital_spin = QDoubleSpinBox()
        self._capital_spin.setRange(100, 100_000_000)
        self._capital_spin.setDecimals(0)
        self._capital_spin.setValue(50000)
        self._capital_spin.setPrefix("$ ")
        self._capital_spin.setMinimumHeight(34)
        form.addRow("初始资金（美元）*", self._capital_spin)

        layout.addLayout(form)

        # 年化预览标签
        self._annualized_label = QLabel("")
        self._annualized_label.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px;"
        )
        layout.addWidget(self._annualized_label)

        self._target_spin.valueChanged.connect(self._update_preview)
        self._start_date.dateChanged.connect(self._update_preview)
        self._end_date.dateChanged.connect(self._update_preview)
        self._update_preview()

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认创建")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_preview(self) -> None:
        try:
            target_pct = self._target_spin.value() / 100
            start = self._start_date.date().toPyDate()
            end   = self._end_date.date().toPyDate()
            days  = max(1, (end - start).days)
            annual = target_pct * 365 / days
            self._annualized_label.setText(
                f"约合年化：{annual*100:.1f}%（共 {days} 天）"
            )
        except Exception:
            pass

    def _on_ok(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "输入错误", "请输入目标名称")
            return

        start = self._start_date.date()
        end   = self._end_date.date()
        if start >= end:
            QMessageBox.warning(self, "输入错误", "结束日期必须晚于开始日期")
            return

        period_map = {0: "MONTHLY", 1: "QUARTERLY", 2: "YEARLY"}
        period = period_map.get(self._period_combo.currentIndex(), "QUARTERLY")

        self._result = {
            "name":              name,
            "period_type":       period,
            "target_return_pct": self._target_spin.value() / 100,
            "start_date":        start.toString("yyyy-MM-dd"),
            "end_date":          end.toString("yyyy-MM-dd"),
            "initial_capital":   self._capital_spin.value(),
        }
        self.accept()

    @property
    def result_data(self) -> Optional[dict]:
        return self._result


class GoalPage(QWidget):
    """盈利目标页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._risk_profile = "moderate"
        self._setup_ui()
        self._connect_events()
        QTimer.singleShot(500, self._refresh_goals)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        # ── 标题行 ──
        header_row = QHBoxLayout()
        title = QLabel("🎯 盈利目标")
        title.setObjectName("page_title")
        header_row.addWidget(title)
        header_row.addStretch()

        header_row.addWidget(QLabel("风险偏好："))
        self._risk_combo = QComboBox()
        self._risk_combo.addItems(["稳健型", "平衡型", "进取型"])
        self._risk_combo.setCurrentIndex(1)
        self._risk_combo.currentIndexChanged.connect(self._on_risk_changed)
        header_row.addWidget(self._risk_combo)

        new_btn = QPushButton("➕ 新建目标")
        new_btn.clicked.connect(self._on_new_goal)
        header_row.addWidget(new_btn)

        layout.addLayout(header_row)

        # ── 风险档位说明卡片 ──
        self._profile_card = QFrame()
        self._profile_card.setObjectName("card")
        pc_layout = QHBoxLayout(self._profile_card)
        self._profile_info = QLabel()
        self._profile_info.setWordWrap(True)
        self._profile_info.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:12px;")
        pc_layout.addWidget(self._profile_info)
        layout.addWidget(self._profile_card)
        self._update_profile_card()

        # ── 目标卡片列表（可滚动）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_widget = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setSpacing(12)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_widget)
        layout.addWidget(scroll, stretch=1)

        # 空态提示
        self._empty_label = QLabel("暂无盈利目标，点击「新建目标」开始")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:14px; "
            f"border:1px dashed {COLORS['border']}; border-radius:12px; padding:60px;"
        )
        layout.addWidget(self._empty_label)
        self._empty_label.hide()

    def _connect_events(self) -> None:
        try:
            from core.event_bus import get_event_bus
            get_event_bus().portfolio_updated.connect(self._refresh_goals)
        except Exception:
            pass

    def _on_risk_changed(self, idx: int) -> None:
        map_ = {0: "conservative", 1: "moderate", 2: "aggressive"}
        self._risk_profile = map_.get(idx, "moderate")
        self._update_profile_card()
        self._refresh_goals()

    def _update_profile_card(self) -> None:
        from goal_planning.goal_manager import STRATEGY_PROFILES
        profile = STRATEGY_PROFILES.get(self._risk_profile, STRATEGY_PROFILES["moderate"])
        low  = profile["annual_return_low"]  * 100
        high = profile["annual_return_high"] * 100
        dd   = abs(profile["max_drawdown"])  * 100
        self._profile_info.setText(
            f"【{profile['label']}】  "
            f"预期年化：{low:.0f}%-{high:.0f}%   "
            f"最大回撤容忍：{dd:.0f}%   "
            f"推荐持股：{profile['max_positions']} 支   "
            f"再平衡：{profile['rebalance']}"
        )

    def _refresh_goals(self) -> None:
        """重新加载并渲染所有目标卡片"""
        # 清空旧卡片（保留最后的 stretch）
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            from goal_planning.goal_manager import get_goal_manager
            manager = get_goal_manager()
            goals   = manager.get_all_goals()

            if not goals:
                self._empty_label.show()
                return
            self._empty_label.hide()

            # 获取当前持仓市值（用于进度计算）
            try:
                from portfolio.manager import get_portfolio_manager
                summary = get_portfolio_manager().get_summary()
                total_value = summary.get("total_market_value")
            except Exception:
                total_value = None

            for goal in goals:
                try:
                    prog = manager.calc_progress(goal, total_value)
                    rec  = manager.recommend_strategy(goal, self._risk_profile, total_value)
                except Exception:
                    prog = None
                    rec  = None

                card = _GoalCard(goal, prog, rec)
                # 插入到 stretch 之前
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

        except Exception as e:
            self._empty_label.setText(f"加载目标失败：{e}")
            self._empty_label.show()

    def _on_new_goal(self) -> None:
        dialog = NewGoalDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.result_data
            if not data:
                return
            try:
                from goal_planning.goal_manager import get_goal_manager
                get_goal_manager().create_goal(**data)
                self._refresh_goals()
            except Exception as e:
                QMessageBox.critical(self, "创建失败", str(e))
