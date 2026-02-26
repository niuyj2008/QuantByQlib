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
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from ui.theme import COLORS


# 策略定义
STRATEGIES = [
    {
        "key":  "deep_learning",
        "name": "深度学习集成",
        "icon": "🧠",
        "model": "Transformer + LSTM + Attention",
        "desc": "融合多种深度学习架构，适合捕捉复杂非线性关系",
        "risk": "平衡型",
        "risk_color": COLORS["warning"],
        "topk": 50,
    },
    {
        "key":  "intraday_profit",
        "name": "短线获利",
        "icon": "⚡",
        "model": "GRU 短序列模型",
        "desc": "捕捉短期动量效应，适合活跃交易者，持仓周期较短",
        "risk": "进取型",
        "risk_color": COLORS["danger"],
        "topk": 30,
    },
    {
        "key":  "growth_stocks",
        "name": "成长股选股",
        "icon": "🌱",
        "model": "LightGBM + 动量因子",
        "desc": "聚焦高成长潜力股票，适合中长期持有，回撤相对较小",
        "risk": "稳健型",
        "risk_color": COLORS["success"],
        "topk": 50,
    },
    {
        "key":  "market_adaptive",
        "name": "市场自适应",
        "icon": "🔄",
        "model": "HMM 政体切换 + LightGBM",
        "desc": "HMM检测牛熊震荡市，自动切换参数，适应市场周期变化",
        "risk": "平衡型",
        "risk_color": COLORS["warning"],
        "topk": 50,
    },
    {
        "key":  "pytorch_full_market",
        "name": "全市场深度学习",
        "icon": "🌐",
        "model": "PyTorch MLP（Alpha360）",
        "desc": "覆盖NYSE+NASDAQ全市场5000+股票，挖掘被忽视的机会",
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

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.screening_progress.connect(self._on_progress)
        bus.screening_completed.connect(self._on_completed)
        bus.screening_failed.connect(self._on_failed)

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
