"""
交易信号页面
显示由选股结果生成的 BUY/SELL/HOLD 彩色信号表格
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ui.theme import COLORS


_SIGNAL_COLORS = {
    "BUY":        COLORS["success"],
    "STRONG_BUY": COLORS["success"],
    "SELL":       COLORS["danger"],
    "HOLD":       COLORS["warning"],
    "WATCH":      COLORS["info"],
}

_STRENGTH_COLORS = {
    "强": COLORS["success"],
    "中": COLORS["warning"],
    "弱": COLORS["text_muted"],
}


class SignalsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_signals: list = []
        self._setup_ui()
        self._connect_events()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        # ── 标题行 ──
        header_row = QHBoxLayout()
        title = QLabel("⚡ 交易信号")
        title.setObjectName("page_title")
        header_row.addWidget(title)
        header_row.addStretch()

        # 信号类型筛选
        header_row.addWidget(QLabel("筛选："))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "买入", "卖出", "持有/观察"])
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        header_row.addWidget(self._filter_combo)

        # 导出
        export_btn = QPushButton("📥 导出信号")
        export_btn.setObjectName("btn_secondary")
        export_btn.clicked.connect(self._on_export)
        header_row.addWidget(export_btn)

        layout.addLayout(header_row)

        # ── 统计摘要行 ──
        self._summary_card = QFrame()
        self._summary_card.setObjectName("card")
        sc_layout = QHBoxLayout(self._summary_card)
        sc_layout.setSpacing(24)

        self._buy_count  = self._stat_label("买入", "0", COLORS["success"])
        self._sell_count = self._stat_label("卖出", "0", COLORS["danger"])
        self._hold_count = self._stat_label("持有/观察", "0", COLORS["warning"])
        self._port_count = self._stat_label("涉及持仓", "0", COLORS["primary"])

        for w in [self._buy_count, self._sell_count,
                  self._hold_count, self._port_count]:
            sc_layout.addWidget(w)
        sc_layout.addStretch()

        self._gen_time_label = QLabel("")
        self._gen_time_label.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:11px;"
        )
        sc_layout.addWidget(self._gen_time_label)
        self._summary_card.hide()
        layout.addWidget(self._summary_card)

        # ── 信号表格 ──
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "股票", "信号", "强度", "Qlib 评分", "今日涨跌", "持仓", "信号原因"
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, stretch=1)

        # 空态占位
        self._placeholder = QLabel(
            "暂无交易信号\n\n请先在「量化选股」页运行策略，选股完成后将自动生成信号"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color:{COLORS['text_muted']}; font-size:13px; padding:40px;"
        )
        layout.addWidget(self._placeholder)

    def _stat_label(self, title: str, value: str, color: str) -> QLabel:
        lbl = QLabel(f"{title}：<b style='color:{color};font-size:16px;'>{value}</b>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        return lbl

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        get_event_bus().screening_completed.connect(self._on_screening_completed)

    def _on_screening_completed(self, results: list) -> None:
        """选股完成后自动生成并显示信号"""
        from signals.signal_generator import SignalGenerator
        try:
            signals = SignalGenerator().generate(results)
            self.load_signals(signals)
        except Exception as e:
            self._placeholder.setText(f"信号生成失败：{e}")

    def load_signals(self, signals: list) -> None:
        """加载并显示信号列表"""
        self._all_signals = signals
        self._apply_filter()
        self._update_summary()

    def _populate_table(self, signals: list) -> None:
        self._table.setRowCount(0)
        if not signals:
            self._placeholder.show()
            self._table.hide()
            return

        self._placeholder.hide()
        self._table.show()
        self._summary_card.show()

        for sig in signals:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # 股票
            ticker_item = QTableWidgetItem(sig.ticker)
            bold = QFont()
            bold.setBold(True)
            ticker_item.setFont(bold)

            # 信号
            sig_color = _SIGNAL_COLORS.get(sig.signal, COLORS["text_muted"])
            signal_item = QTableWidgetItem(sig.signal_zh)
            signal_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            signal_item.setForeground(QColor(sig_color))
            bold2 = QFont()
            bold2.setBold(True)
            signal_item.setFont(bold2)

            # 强度
            str_color = _STRENGTH_COLORS.get(sig.strength, COLORS["text_muted"])
            strength_item = QTableWidgetItem(sig.strength)
            strength_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            strength_item.setForeground(QColor(str_color))

            # 评分
            score_item = QTableWidgetItem(f"{sig.score:.4f}")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # 涨跌幅
            change = sig.change_pct
            if change is not None:
                sign = "+" if change >= 0 else ""
                change_text  = f"{sign}{change:.2f}%"
                change_color = COLORS["success"] if change >= 0 else COLORS["danger"]
            else:
                change_text, change_color = "--", COLORS["text_muted"]
            change_item = QTableWidgetItem(change_text)
            change_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            change_item.setForeground(QColor(change_color))

            # 持仓
            port_item = QTableWidgetItem("持仓" if sig.in_portfolio else "--")
            port_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if sig.in_portfolio:
                port_item.setForeground(QColor(COLORS["primary"]))

            # 原因
            reason_item = QTableWidgetItem(sig.reason)
            reason_item.setForeground(QColor(COLORS["text_secondary"]))

            for col, item in enumerate([
                ticker_item, signal_item, strength_item,
                score_item, change_item, port_item, reason_item
            ]):
                self._table.setItem(row, col, item)

    def _update_summary(self) -> None:
        sigs = self._all_signals
        buy_n  = sum(1 for s in sigs if s.signal in ("BUY", "STRONG_BUY"))
        sell_n = sum(1 for s in sigs if s.signal == "SELL")
        hold_n = sum(1 for s in sigs if s.signal in ("HOLD", "WATCH"))
        port_n = sum(1 for s in sigs if s.in_portfolio)

        def _upd(lbl, title, n, color):
            lbl.setText(
                f"{title}：<b style='color:{color};font-size:16px;'>{n}</b>"
            )

        _upd(self._buy_count,  "买入",    buy_n,  COLORS["success"])
        _upd(self._sell_count, "卖出",    sell_n, COLORS["danger"])
        _upd(self._hold_count, "持有/观察", hold_n, COLORS["warning"])
        _upd(self._port_count, "涉及持仓", port_n, COLORS["primary"])

        if sigs:
            self._gen_time_label.setText(
                f"生成时间：{sigs[0].generated_at}"
            )
        self._summary_card.show()

    def _apply_filter(self) -> None:
        f = self._filter_combo.currentText()
        if f == "买入":
            filtered = [s for s in self._all_signals
                        if s.signal in ("BUY", "STRONG_BUY")]
        elif f == "卖出":
            filtered = [s for s in self._all_signals if s.signal == "SELL"]
        elif f == "持有/观察":
            filtered = [s for s in self._all_signals
                        if s.signal in ("HOLD", "WATCH")]
        else:
            filtered = self._all_signals
        self._populate_table(filtered)

    def _on_export(self) -> None:
        if not self._all_signals:
            return
        from PyQt6.QtWidgets import QFileDialog
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "导出信号", "交易信号.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "股票", "信号", "强度", "Qlib评分",
                "今日涨跌%", "持仓", "信号原因", "生成时间"
            ])
            for s in self._all_signals:
                writer.writerow([
                    s.ticker, s.signal_zh, s.strength,
                    f"{s.score:.4f}",
                    f"{s.change_pct:.2f}" if s.change_pct is not None else "",
                    "是" if s.in_portfolio else "否",
                    s.reason, s.generated_at,
                ])
