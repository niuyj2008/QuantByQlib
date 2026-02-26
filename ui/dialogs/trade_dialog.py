"""
买入 / 卖出 交易对话框
- 输入：股票代码、股数、价格、佣金、日期、备注
- 实时显示预计金额
- 完整输入校验
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDoubleSpinBox,
    QDateEdit, QTextEdit, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont

from ui.theme import COLORS


class TradeDialog(QDialog):
    """
    通用交易对话框（买入/卖出两用）
    trade_type: "buy" | "sell"
    ticker: 预填股票代码（从持仓表格点击时传入）
    """

    def __init__(self, trade_type: Literal["buy", "sell"] = "buy",
                 ticker: str = "", parent=None):
        super().__init__(parent)
        self.trade_type = trade_type
        self._result_data: dict | None = None

        title = "记录买入" if trade_type == "buy" else "记录卖出"
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._setup_ui(ticker)

    def _setup_ui(self, ticker: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── 标题 ─────────────────────────────────────────
        is_buy = self.trade_type == "buy"
        color = COLORS["success"] if is_buy else COLORS["danger"]
        icon = "📈 买入" if is_buy else "📉 卖出"

        header = QLabel(icon)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        header.setFont(font)
        header.setStyleSheet(f"color: {color};")
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # ── 股票代码 ──────────────────────────────────────
        layout.addWidget(self._label("股票代码 *"))
        self._ticker_input = QLineEdit(ticker.upper())
        self._ticker_input.setPlaceholderText("例：NVDA、AAPL、MSFT")
        self._ticker_input.setMinimumHeight(36)
        self._ticker_input.textChanged.connect(self._update_preview)
        layout.addWidget(self._ticker_input)

        # ── 股数 ─────────────────────────────────────────
        layout.addWidget(self._label("股数 *"))
        self._shares_input = QDoubleSpinBox()
        self._shares_input.setMinimum(0.001)
        self._shares_input.setMaximum(9_999_999)
        self._shares_input.setDecimals(3)
        self._shares_input.setSingleStep(1)
        self._shares_input.setValue(100)
        self._shares_input.setMinimumHeight(36)
        self._shares_input.valueChanged.connect(self._update_preview)
        layout.addWidget(self._shares_input)

        # ── 成交价格 ──────────────────────────────────────
        layout.addWidget(self._label("成交价格（美元）*"))
        self._price_input = QDoubleSpinBox()
        self._price_input.setMinimum(0.001)
        self._price_input.setMaximum(999_999)
        self._price_input.setDecimals(4)
        self._price_input.setSingleStep(0.01)
        self._price_input.setPrefix("$")
        self._price_input.setMinimumHeight(36)
        self._price_input.valueChanged.connect(self._update_preview)
        layout.addWidget(self._price_input)

        # ── 佣金 ─────────────────────────────────────────
        layout.addWidget(self._label("佣金（美元，默认 $0）"))
        self._commission_input = QDoubleSpinBox()
        self._commission_input.setMinimum(0)
        self._commission_input.setMaximum(9999)
        self._commission_input.setDecimals(2)
        self._commission_input.setPrefix("$")
        self._commission_input.setValue(0.0)
        self._commission_input.setMinimumHeight(36)
        self._commission_input.valueChanged.connect(self._update_preview)
        layout.addWidget(self._commission_input)

        # ── 交易日期 ──────────────────────────────────────
        layout.addWidget(self._label("交易日期 *"))
        self._date_input = QDateEdit(QDate.currentDate())
        self._date_input.setCalendarPopup(True)
        self._date_input.setMinimumHeight(36)
        self._date_input.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(self._date_input)

        # ── 备注 ─────────────────────────────────────────
        layout.addWidget(self._label("备注（可选）"))
        self._notes_input = QTextEdit()
        self._notes_input.setMaximumHeight(60)
        self._notes_input.setPlaceholderText("策略来源、信号原因等...")
        layout.addWidget(self._notes_input)

        # ── 预计金额预览 ──────────────────────────────────
        self._preview_card = QFrame()
        self._preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(self._preview_card)
        preview_layout.setSpacing(4)

        self._preview_label = QLabel("预计总金额：--")
        preview_font = QFont()
        preview_font.setPointSize(14)
        preview_font.setBold(True)
        self._preview_label.setFont(preview_font)
        self._preview_label.setStyleSheet(f"color: {color};")
        preview_layout.addWidget(self._preview_label)

        self._preview_sub = QLabel("")
        self._preview_sub.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        preview_layout.addWidget(self._preview_sub)

        layout.addWidget(self._preview_card)

        # ── 按钮行 ────────────────────────────────────────
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("btn_secondary")
        cancel_btn.setMinimumHeight(38)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_text = "✅ 确认买入" if is_buy else "✅ 确认卖出"
        self._confirm_btn = QPushButton(confirm_text)
        self._confirm_btn.setMinimumHeight(38)
        if not is_buy:
            self._confirm_btn.setObjectName("btn_danger")
        self._confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._confirm_btn)

        layout.addLayout(btn_row)
        self._update_preview()

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        return lbl

    def _update_preview(self) -> None:
        """实时更新预计金额"""
        shares = self._shares_input.value()
        price  = self._price_input.value()
        comm   = self._commission_input.value()
        subtotal = shares * price
        total    = subtotal + comm if self.trade_type == "buy" else subtotal - comm

        self._preview_label.setText(f"{'总计' if self.trade_type == 'buy' else '到账'} ${total:,.2f}")
        self._preview_sub.setText(
            f"{shares:.3g} 股 × ${price:.4f} = ${subtotal:,.2f}"
            + (f"   +佣金 ${comm:.2f}" if comm > 0 and self.trade_type == "buy"
               else f"   -佣金 ${comm:.2f}" if comm > 0 else "")
        )

    def _on_confirm(self) -> None:
        """校验并收集表单数据"""
        from utils.validators import validate_ticker

        ticker = self._ticker_input.text().strip().upper()
        ok, err = validate_ticker(ticker)
        if not ok:
            QMessageBox.warning(self, "输入错误", err)
            self._ticker_input.setFocus()
            return

        shares = self._shares_input.value()
        price  = self._price_input.value()
        if shares <= 0 or price <= 0:
            QMessageBox.warning(self, "输入错误", "股数和价格必须大于 0")
            return

        # 卖出时检查持仓是否足够
        if self.trade_type == "sell":
            from portfolio.db import get_db
            pos = get_db().get_position(ticker)
            if not pos:
                QMessageBox.warning(self, "持仓不足",
                    f"您没有持有 {ticker} 的股票，无法卖出。")
                return
            if pos["shares"] < shares - 1e-6:
                QMessageBox.warning(self, "持仓不足",
                    f"{ticker} 持仓 {pos['shares']:.3g} 股，"
                    f"尝试卖出 {shares:.3g} 股，数量不足。")
                return

        self._result_data = {
            "ticker":      ticker,
            "shares":      shares,
            "price":       price,
            "commission":  self._commission_input.value(),
            "trans_date":  self._date_input.date().toString("yyyy-MM-dd"),
            "notes":       self._notes_input.toPlainText().strip() or None,
        }
        self.accept()

    @property
    def result_data(self) -> dict | None:
        """对话框确认后通过此属性获取交易数据"""
        return self._result_data


class DeleteConfirmDialog(QDialog):
    """删除持仓确认对话框"""

    def __init__(self, symbol: str, shares: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认删除持仓")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        warn = QLabel("⚠️ 确认删除持仓？")
        warn.setStyleSheet(f"color: {COLORS['warning']}; font-size: 15px; font-weight: bold;")
        layout.addWidget(warn)

        msg = QLabel(
            f"将从持仓记录中删除 <b>{symbol}</b>（{shares:.3g} 股）。\n\n"
            "此操作不会记录卖出交易，仅删除持仓数据（用于纠错）。\n"
            "历史交易记录不受影响。"
        )
        msg.setStyleSheet(f"color: {COLORS['text_secondary']};")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("btn_secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        del_btn = QPushButton("确认删除")
        del_btn.setObjectName("btn_danger")
        del_btn.clicked.connect(self.accept)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)
