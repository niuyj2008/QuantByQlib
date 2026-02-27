"""
量化选股页面
- 5种 Qlib 策略卡片选择
- 参数配置
- 运行控制（开始/停止）
- 进度显示
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGridLayout, QFrame, QProgressBar,
    QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from ui.theme import COLORS


# 策略定义
STRATEGIES = [
    {
        "key":  "deep_learning",
        "name": "深度学习集成",
        "icon": "🧠",
        "model": "Qlib LSTM（Alpha158，2层，hidden=64）",
        "desc": "LSTM 时序模型捕捉价量非线性关系，适合中长期趋势跟踪",
        "risk": "平衡型",
        "risk_color": COLORS["warning"],
        "topk": 50,
    },
    {
        "key":  "intraday_profit",
        "name": "短线获利",
        "icon": "⚡",
        "model": "Qlib GRU（Alpha158，短窗口 126天训练）",
        "desc": "GRU 捕捉短期动量效应，训练窗口短，适合活跃交易者",
        "risk": "进取型",
        "risk_color": COLORS["danger"],
        "topk": 30,
    },
    {
        "key":  "growth_stocks",
        "name": "成长股选股",
        "icon": "🌱",
        "model": "LightGBM（Alpha158，158个因子）",
        "desc": "梯度提升树聚焦成长因子，适合中长期持有，回撤相对较小",
        "risk": "稳健型",
        "risk_color": COLORS["success"],
        "topk": 50,
    },
    {
        "key":  "market_adaptive",
        "name": "市场自适应",
        "icon": "🔄",
        "model": "LightGBM（Alpha158，牛熊自适应学习率）",
        "desc": "检测市场政体自动切换学习率参数，适应不同市场周期",
        "risk": "平衡型",
        "risk_color": COLORS["warning"],
        "topk": 50,
    },
    {
        "key":  "pytorch_full_market",
        "name": "全市场深度学习",
        "icon": "🌐",
        "model": "Qlib LSTM（Alpha360，360个因子）",
        "desc": "Alpha360 宽因子集 + LSTM，覆盖全市场蓝筹股，挖掘被忽视的机会",
        "risk": "进取型",
        "risk_color": COLORS["danger"],
        "topk": 50,
    },
]


class StrategyCard(QFrame):
    """策略选择卡片"""

    selected = pyqtSignal(str)   # 策略 key

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._is_selected = False
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(160)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # 标题行
        title_row = QHBoxLayout()
        icon_lbl = QLabel(self.config["icon"])
        icon_lbl.setStyleSheet("font-size: 24px;")
        title_row.addWidget(icon_lbl)

        name_lbl = QLabel(self.config["name"])
        name_font = QFont()
        name_font.setPointSize(14)
        name_font.setBold(True)
        name_lbl.setFont(name_font)
        title_row.addWidget(name_lbl)
        title_row.addStretch()

        # 风险标签
        risk_lbl = QLabel(self.config["risk"])
        risk_lbl.setStyleSheet(
            f"color: {self.config['risk_color']}; "
            f"border: 1px solid {self.config['risk_color']}55; "
            f"border-radius: 8px; padding: 2px 8px; font-size: 11px;"
        )
        title_row.addWidget(risk_lbl)
        layout.addLayout(title_row)

        # 模型名
        model_lbl = QLabel(self.config["model"])
        model_lbl.setStyleSheet(f"color: {COLORS['primary_light']}; font-size: 11px;")
        layout.addWidget(model_lbl)

        # 描述
        desc_lbl = QLabel(self.config["desc"])
        desc_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        layout.addStretch()

        # 底部：选股数量
        topk_lbl = QLabel(f"目标选出：Top {self.config['topk']} 支")
        topk_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(topk_lbl)

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        if selected:
            self.setStyleSheet(
                f"QFrame#card {{ border: 2px solid {COLORS['primary']}; "
                f"background-color: {COLORS['bg_card_hover']}; border-radius: 12px; }}"
            )
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.config["key"])
        super().mousePressEvent(event)


class ScreeningPage(QWidget):
    """量化选股页面"""

    run_requested = pyqtSignal(str)    # 策略 key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_strategy = "deep_learning"
        self._strategy_cards: dict[str, StrategyCard] = {}
        self._setup_ui()
        self._connect_events()
        # 默认选中第一个策略
        self._on_strategy_selected("deep_learning")
        # 延迟加载已注入因子状态
        QTimer.singleShot(800, self._refresh_injected_factors)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(16)

        # 页面标题
        title = QLabel("⚙️ 量化选股")
        title.setObjectName("page_title")
        layout.addWidget(title)

        subtitle = QLabel("选择 Qlib 量化策略，系统将从美股全市场筛选最优个股组合")
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(subtitle)

        # ── 策略卡片网格（2×3布局）────────────────────────
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, s in enumerate(STRATEGIES):
            card = StrategyCard(s)
            card.selected.connect(self._on_strategy_selected)
            self._strategy_cards[s["key"]] = card
            row, col = divmod(i, 3)
            grid.addWidget(card, row, col)

        # 补空格（保持网格对齐）
        if len(STRATEGIES) % 3 != 0:
            for j in range(len(STRATEGIES) % 3, 3):
                placeholder = QWidget()
                grid.addWidget(placeholder, len(STRATEGIES) // 3, j)

        layout.addLayout(grid)

        # ── 运行控制区 ────────────────────────────────────
        control_card = QFrame()
        control_card.setObjectName("card")
        control_layout = QVBoxLayout(control_card)
        control_layout.setSpacing(10)

        # 当前选中策略
        self._selected_label = QLabel("已选策略：深度学习集成")
        self._selected_label.setStyleSheet(
            f"color: {COLORS['primary_light']}; font-weight: bold; font-size: 14px;"
        )
        control_layout.addWidget(self._selected_label)

        # ── 已注入因子面板 ────────────────────────────
        injected_frame = QFrame()
        injected_frame.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}55; "
            f"border: 1px solid {COLORS['border']}44; border-radius: 6px; }}"
        )
        injected_inner = QVBoxLayout(injected_frame)
        injected_inner.setContentsMargins(8, 6, 8, 6)
        injected_inner.setSpacing(3)

        injected_title_row = QHBoxLayout()
        injected_title = QLabel("🧬 已注入自定义因子")
        injected_title.setStyleSheet(
            f"color:{COLORS['text_secondary']}; font-size:11px; font-weight:bold;"
            f" border:none; background:transparent;"
        )
        injected_title_row.addWidget(injected_title)
        injected_title_row.addStretch()
        self._injected_count_lbl = QLabel("无")
        self._injected_count_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px;"
            f" border:none; background:transparent;"
        )
        injected_title_row.addWidget(self._injected_count_lbl)
        injected_inner.addLayout(injected_title_row)

        # 因子标签滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(80)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._inj_tags_widget = QWidget()
        self._inj_tags_widget.setStyleSheet("background: transparent;")
        self._inj_tags_layout = QVBoxLayout(self._inj_tags_widget)
        self._inj_tags_layout.setSpacing(1)
        self._inj_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._inj_tags_layout.addStretch()
        scroll.setWidget(self._inj_tags_widget)
        injected_inner.addWidget(scroll)

        control_layout.addWidget(injected_frame)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setMinimumHeight(10)
        control_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        control_layout.addWidget(self._status_label)

        # 按钮行
        btn_row = QHBoxLayout()

        self._run_btn = QPushButton("▶ 开始选股")
        self._run_btn.setMinimumHeight(42)
        self._run_btn.clicked.connect(self._on_run_clicked)
        btn_row.addWidget(self._run_btn)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setObjectName("btn_danger")
        self._stop_btn.setMinimumHeight(42)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self._stop_btn)

        control_layout.addLayout(btn_row)
        layout.addWidget(control_card)

    def _on_strategy_selected(self, key: str) -> None:
        # 取消旧选中
        if self._selected_strategy in self._strategy_cards:
            self._strategy_cards[self._selected_strategy].set_selected(False)
        # 激活新选中
        self._selected_strategy = key
        if key in self._strategy_cards:
            self._strategy_cards[key].set_selected(True)
        # 更新标签
        name = next((s["name"] for s in STRATEGIES if s["key"] == key), key)
        self._selected_label.setText(f"已选策略：{name}")

    def _on_run_clicked(self) -> None:
        from core.app_state import get_state
        state = get_state()
        if not state.qlib_initialized:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Qlib 未初始化",
                "请先前往「参数配置」下载 Qlib 美股数据后再运行选股。")
            return
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self.run_requested.emit(self._selected_strategy)

    def _on_stop_clicked(self) -> None:
        from core.event_bus import get_event_bus
        get_event_bus().screening_failed.emit("用户手动停止")

    def _build_inj_tags(self, factors: list) -> None:
        """在 _inj_tags_layout 中为每个因子创建带 tooltip 的标签行"""
        while self._inj_tags_layout.count() > 1:
            item = self._inj_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not factors:
            lbl = QLabel("暂无注入因子，LightGBM 策略将使用标准 Alpha158")
            lbl.setStyleSheet(
                f"color:{COLORS['text_muted']}; font-size:10px; border:none; background:transparent;"
            )
            self._inj_tags_layout.insertWidget(0, lbl)
            self._injected_count_lbl.setText("无")
            return

        self._injected_count_lbl.setText(f"共 {len(factors)} 个（仅 LightGBM 策略使用）")
        for i, f in enumerate(factors):
            expr = f.get("expression", "") if isinstance(f, dict) else str(f)
            name = f.get("name", "")        if isinstance(f, dict) else ""
            desc = f.get("description", "") if isinstance(f, dict) else ""

            display = f"• {name}：{expr[:38]}{'…' if len(expr) > 38 else ''}" if name \
                      else f"• {expr[:48]}{'…' if len(expr) > 48 else ''}"

            lbl = QLabel(display)
            lbl.setStyleSheet(
                f"color:{COLORS['text_secondary']}; font-size:10px; "
                f"border:none; background:transparent; padding:0px 2px;"
            )
            lbl.setCursor(Qt.CursorShape.WhatsThisCursor)

            tooltip_lines = []
            if name:
                tooltip_lines.append(f"<b>{name}</b>")
            if desc:
                tooltip_lines.append(desc)
            tooltip_lines.append(f"<code>{expr}</code>")
            lbl.setToolTip("<br>".join(tooltip_lines))
            lbl.setTextFormat(Qt.TextFormat.PlainText)

            self._inj_tags_layout.insertWidget(i, lbl)

    def _refresh_injected_factors(self) -> None:
        """读取 valid_factors.json 并刷新因子面板"""
        try:
            from strategies.factor_injector import get_inject_status
            status = get_inject_status()
            self._build_inj_tags(status.get("factors", []))
        except Exception:
            self._build_inj_tags([])

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.screening_progress.connect(self._on_progress)
        bus.screening_completed.connect(self._on_completed)
        bus.screening_failed.connect(self._on_failed)
        # 因子注入完成后自动刷新面板
        bus.rdagent_factors_injected.connect(self._build_inj_tags)

    def _on_progress(self, pct: int, msg: str) -> None:
        self._progress_bar.setValue(pct)
        self._status_label.setText(msg)

    def _on_completed(self, results: list) -> None:
        self._reset_controls()
        count = len(results)
        self._status_label.setText(f"✅ 选股完成，共筛出 {count} 支股票，已跳转到选股结果页")
        from core.event_bus import get_event_bus
        get_event_bus().navigate_to.emit("results")

    def _on_failed(self, err: str) -> None:
        self._reset_controls()
        self._status_label.setText(f"❌ 选股失败：{err}")

    def _reset_controls(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setVisible(False)
