"""
持仓管理页面（阶段三：真实数据版本）
- 概览：总市值/盈亏/今日盈亏/已实现盈亏
- 持仓明细表格（含实时价格刷新）
- 交易记录标签页
- 风险分析标签页
"""
from __future__ import annotations

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QHeaderView, QFrame, QMessageBox,
    QMenu, QProgressDialog,
)
from PyQt6.QtCore import Qt, QTimer, QThreadPool
from PyQt6.QtGui import QColor, QFont
from ui.theme import COLORS
from utils.formatters import fmt_price, fmt_pct, fmt_shares


class PortfolioPage(QWidget):
    """持仓管理页面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._positions: list[dict] = []
        self._refresh_timer = QTimer(self)
        self._setup_ui()
        self._connect_events()
        self._refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(16)

        # ── 标题行 ────────────────────────────────────────
        header_row = QHBoxLayout()
        title = QLabel("💼 持仓管理")
        title.setObjectName("page_title")
        header_row.addWidget(title)
        header_row.addStretch()

        self._refresh_btn = QPushButton("🔄 刷新价格")
        self._refresh_btn.setObjectName("btn_secondary")
        self._refresh_btn.clicked.connect(self._on_refresh_prices)
        header_row.addWidget(self._refresh_btn)

        self._export_charts_btn = QPushButton("📊 批量导出图表")
        self._export_charts_btn.setObjectName("btn_secondary")
        self._export_charts_btn.clicked.connect(self._on_export_charts)
        header_row.addWidget(self._export_charts_btn)

        buy_btn = QPushButton("📈 买入")
        buy_btn.clicked.connect(self._on_buy)
        header_row.addWidget(buy_btn)

        sell_btn = QPushButton("📉 卖出")
        sell_btn.setObjectName("btn_danger")
        sell_btn.clicked.connect(lambda: self._on_sell())
        header_row.addWidget(sell_btn)
        layout.addLayout(header_row)

        # ── KPI 指标行 ────────────────────────────────────
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self._card_invested   = self._make_metric_card("总投入成本", "$--")
        self._card_value      = self._make_metric_card("总持仓市值", "$--")
        self._card_unreal_pnl = self._make_metric_card("未实现盈亏", "--")
        self._card_realized   = self._make_metric_card("已实现盈亏", "--")
        self._card_today      = self._make_metric_card("今日盈亏",   "--")
        for c in [self._card_invested, self._card_value,
                  self._card_unreal_pnl, self._card_realized, self._card_today]:
            metrics_row.addWidget(c)
        layout.addLayout(metrics_row)

        # ── 标签页 ────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_holdings_tab(),     "📊 持仓明细")
        self._tabs.addTab(self._build_transactions_tab(), "📋 交易记录")
        self._tabs.addTab(self._build_risk_tab(),         "⚠️ 风险分析")
        layout.addWidget(self._tabs, stretch=1)

    def _make_metric_card(self, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        lay.addWidget(t)
        v = QLabel(value)
        f = QFont(); f.setPointSize(15); f.setBold(True)
        v.setFont(f)
        lay.addWidget(v)
        card._value_lbl = v
        return card

    # ── Holdings Tab ─────────────────────────────────────

    def _build_holdings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        self._holdings_table = QTableWidget()
        self._holdings_table.setColumnCount(11)
        self._holdings_table.setHorizontalHeaderLabels([
            "股票", "股数", "均价", "现价", "市值", "盈亏$", "盈亏%", "今日", "卖出", "分析", "图表"
        ])
        self._holdings_table.setAlternatingRowColors(True)
        self._holdings_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._holdings_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._holdings_table.verticalHeader().setVisible(False)
        self._holdings_table.verticalHeader().setDefaultSectionSize(44)
        self._holdings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._holdings_table.customContextMenuRequested.connect(self._on_context_menu)
        # 横向滚动条始终显示
        self._holdings_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        hdr = self._holdings_table.horizontalHeader()
        # 所有列固定宽度，总宽约884px，超出时横向滚动
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(0, 72)   # 股票
        hdr.resizeSection(1, 60)   # 股数
        hdr.resizeSection(2, 90)   # 均价
        hdr.resizeSection(3, 100)  # 现价（含*后缀）
        hdr.resizeSection(4, 100)  # 市值
        hdr.resizeSection(5, 100)  # 盈亏$
        hdr.resizeSection(6, 80)   # 盈亏%
        hdr.resizeSection(7, 80)   # 今日
        hdr.resizeSection(8, 64)   # 卖出
        hdr.resizeSection(9, 64)   # 分析
        hdr.resizeSection(10, 64)  # 图表
        lay.addWidget(self._holdings_table)

        self._holdings_empty = QLabel(
            "暂无持仓记录\n\n点击右上角「📈 买入」添加您的第一笔持仓"
        )
        self._holdings_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._holdings_empty.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; padding: 60px;"
        )
        lay.addWidget(self._holdings_empty)

        self._holdings_summary = QLabel("")
        self._holdings_summary.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; padding: 4px 8px;"
        )
        lay.addWidget(self._holdings_summary)
        return w

    # ── Transactions Tab ─────────────────────────────────

    def _build_transactions_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)

        self._trans_table = QTableWidget()
        self._trans_table.setColumnCount(7)
        self._trans_table.setHorizontalHeaderLabels(
            ["日期", "股票", "类型", "股数", "价格", "金额", "备注"]
        )
        self._trans_table.setAlternatingRowColors(True)
        self._trans_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._trans_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._trans_table.verticalHeader().setVisible(False)
        self._trans_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        self._trans_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._trans_table.customContextMenuRequested.connect(self._on_trans_context_menu)
        lay.addWidget(self._trans_table)
        return w

    # ── Risk Tab ─────────────────────────────────────────

    def _build_risk_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(12)

        risk_card = QFrame()
        risk_card.setObjectName("card")
        risk_inner = QVBoxLayout(risk_card)

        self._risk_content = QLabel(
            "切换到「持仓明细」刷新价格后，风险分析将自动计算。"
        )
        self._risk_content.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 13px;")
        self._risk_content.setWordWrap(True)
        self._risk_content.setAlignment(Qt.AlignmentFlag.AlignTop)
        risk_inner.addWidget(self._risk_content)
        lay.addWidget(risk_card)
        lay.addStretch()
        return w

    # ── 事件连接 ──────────────────────────────────────────

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        bus = get_event_bus()
        bus.portfolio_updated.connect(self._refresh)
        self._refresh_timer.timeout.connect(self._on_refresh_prices)
        self._refresh_timer.start(60_000)

    # ── 数据加载 ──────────────────────────────────────────

    def _refresh(self) -> None:
        first_load = not self._positions
        try:
            from portfolio.db import get_db
            db = get_db()
            self._positions = db.get_all_positions()
            self._populate_holdings(self._positions)
            self._populate_transactions(db.get_transactions())
            summary = db.get_portfolio_summary()
            self._update_metrics(summary)
        except Exception as e:
            from loguru import logger
            logger.warning(f"持仓数据加载失败：{e}")
        # 首次加载完持仓数据后，延迟 800ms 自动刷新价格
        if first_load and self._positions:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(800, self._on_refresh_prices)

    def _on_refresh_prices(self) -> None:
        if not self._positions:
            return
        tickers = [p["symbol"] for p in self._positions]
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("⏳ 刷新中...")

        from workers.price_refresh_worker import PriceRefreshWorker
        worker = PriceRefreshWorker(tickers)
        worker.signals.prices_updated.connect(self._on_prices_updated)
        worker.signals.error.connect(lambda _: self._reset_refresh_btn())
        QThreadPool.globalInstance().start(worker)

    def _on_prices_updated(self, quotes: dict) -> None:
        self._reset_refresh_btn()
        if not quotes:
            return

        for row in range(self._holdings_table.rowCount()):
            sym_item = self._holdings_table.item(row, 0)
            if not sym_item:
                continue
            symbol = sym_item.text()
            quote  = quotes.get(symbol)
            if not quote:
                continue

            current_price = quote.get("price")
            change_pct    = quote.get("change_pct")
            is_extended   = quote.get("is_extended", False)
            pos = next((p for p in self._positions if p["symbol"] == symbol), None)
            if not pos or current_price is None:
                continue

            shares     = pos["shares"]
            avg_cost   = pos["avg_cost"]
            market_val = shares * current_price
            pnl        = market_val - shares * avg_cost
            pnl_pct    = pnl / (shares * avg_cost) if avg_cost > 0 else 0

            # 盘前/盘后价格加*标注
            price_text = fmt_price(current_price) + ("*" if is_extended else "")
            price_color = COLORS["warning"] if is_extended else None
            self._set_cell(row, 3, price_text, price_color)
            self._set_cell(row, 4, fmt_price(market_val), None)
            pnl_color = COLORS["success"] if pnl >= 0 else COLORS["danger"]
            self._set_cell(row, 5, fmt_price(pnl, prefix=""), pnl_color)
            self._set_cell(row, 6, fmt_pct(pnl_pct), pnl_color)
            if change_pct is not None:
                c_color = COLORS["success"] if change_pct >= 0 else COLORS["danger"]
                self._set_cell(row, 7, fmt_pct(change_pct / 100), c_color)

        try:
            from portfolio.db import get_db
            current_prices = {s: q.get("price") for s, q in quotes.items() if q and q.get("price")}
            summary = get_db().get_portfolio_summary(current_prices)
            self._update_metrics(summary)
            self._update_risk_tab()
        except Exception:
            pass

    def _reset_refresh_btn(self) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("🔄 刷新价格")

    # ── 填充表格 ──────────────────────────────────────────

    def _populate_holdings(self, positions: list[dict]) -> None:
        has_data = bool(positions)
        self._holdings_table.setVisible(has_data)
        self._holdings_empty.setVisible(not has_data)
        self._holdings_table.setRowCount(0)

        # 按钮内联样式（覆盖全局 QPushButton padding: 8px 18px）
        _sell_style = (
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #991B1B, stop:1 #EF4444); color: white; border: none;"
            " border-radius: 6px; padding: 4px 2px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #DC2626; }"
        )
        _anal_style = (
            "QPushButton { background: transparent; border: 1px solid #5B5BD6;"
            " color: #5B5BD6; border-radius: 6px; padding: 4px 2px;"
            " font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #F0F1F5; }"
        )

        for pos in positions:
            row = self._holdings_table.rowCount()
            self._holdings_table.insertRow(row)
            self._holdings_table.setRowHeight(row, 44)   # 必须明确设置每行高度（44px才能保证按钮完整显示）
            sym      = pos["symbol"]
            shares   = pos["shares"]
            avg_cost = pos["avg_cost"]

            self._set_cell(row, 0, sym, None, bold=True)
            self._set_cell(row, 1, fmt_shares(shares), None)
            self._set_cell(row, 2, fmt_price(avg_cost), None)
            self._set_cell(row, 3, "--", COLORS["text_muted"])                      # 现价
            self._set_cell(row, 4, fmt_price(shares * avg_cost), None)              # 市值（初始用成本）
            self._set_cell(row, 5, "--", COLORS["text_muted"])                      # 盈亏$
            self._set_cell(row, 6, "--", COLORS["text_muted"])                      # 盈亏%
            self._set_cell(row, 7, "--", COLORS["text_muted"])                      # 今日

            # 卖出按钮（第8列）
            sell_w = QWidget()
            sell_lay = QHBoxLayout(sell_w)
            sell_lay.setContentsMargins(4, 4, 4, 4)
            s_btn = QPushButton("卖出")
            s_btn.setStyleSheet(_sell_style)
            s_btn.clicked.connect(lambda _, s=sym: self._on_sell(s))
            sell_lay.addWidget(s_btn)
            self._holdings_table.setCellWidget(row, 8, sell_w)

            # 分析按钮（第9列）
            anal_w = QWidget()
            anal_lay = QHBoxLayout(anal_w)
            anal_lay.setContentsMargins(4, 4, 4, 4)
            d_btn = QPushButton("分析")
            d_btn.setStyleSheet(_anal_style)
            d_btn.clicked.connect(lambda _, s=sym: self._on_show_detail(s))
            anal_lay.addWidget(d_btn)
            self._holdings_table.setCellWidget(row, 9, anal_w)

            # 图表按钮（第10列）
            chart_w = QWidget()
            chart_lay = QHBoxLayout(chart_w)
            chart_lay.setContentsMargins(4, 4, 4, 4)
            c_btn = QPushButton("图表")
            c_btn.setStyleSheet(_anal_style)
            c_btn.clicked.connect(lambda _, s=sym: self._on_show_chart(s))
            chart_lay.addWidget(c_btn)
            self._holdings_table.setCellWidget(row, 10, chart_w)

        self._holdings_summary.setText(
            f"共 {len(positions)} 个持仓" if positions else ""
        )

    def _populate_transactions(self, transactions: list[dict]) -> None:
        self._trans_table.setRowCount(0)
        type_map    = {"BUY": "买入", "SELL": "卖出", "DIVIDEND": "股息", "SPLIT": "拆股"}
        type_colors = {
            "BUY": COLORS["success"], "SELL": COLORS["danger"],
            "DIVIDEND": COLORS["info"], "SPLIT": COLORS["warning"],
        }
        for t in transactions:
            row = self._trans_table.rowCount()
            self._trans_table.insertRow(row)
            ttype = t.get("trans_type", "BUY")
            color = type_colors.get(ttype, COLORS["text_muted"])

            # 日期列同时存储 transaction id，用于删除操作
            date_item = QTableWidgetItem(t.get("trans_date", "--"))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setData(Qt.ItemDataRole.UserRole, t.get("id"))
            self._trans_table.setItem(row, 0, date_item)

            self._set_trans_cell(row, 1, t.get("symbol", "--"), None, bold=True)
            type_item = QTableWidgetItem(type_map.get(ttype, ttype))
            type_item.setForeground(QColor(color))
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._trans_table.setItem(row, 2, type_item)
            self._set_trans_cell(row, 3, fmt_shares(t.get("shares")), None)
            self._set_trans_cell(row, 4, fmt_price(t.get("price")), None)
            self._set_trans_cell(row, 5, fmt_price(t.get("amount")), None)
            self._set_trans_cell(row, 6, t.get("notes") or "", None)

    def _update_metrics(self, summary: dict) -> None:
        def c(v):
            return COLORS["success"] if v >= 0 else COLORS["danger"]

        self._card_invested._value_lbl.setText(fmt_price(summary["total_invested"]))
        self._card_value._value_lbl.setText(fmt_price(summary["total_market_value"]))

        unreal = summary["total_unrealized_pnl"]
        self._card_unreal_pnl._value_lbl.setText(
            f"{fmt_price(unreal, prefix='')}\n{fmt_pct(summary['total_unrealized_pct'])}"
        )
        self._card_unreal_pnl._value_lbl.setStyleSheet(
            f"color: {c(unreal)}; font-size: 14px; font-weight: bold;"
        )

        realized = summary["total_realized_pnl"]
        self._card_realized._value_lbl.setText(fmt_price(realized, prefix=""))
        self._card_realized._value_lbl.setStyleSheet(
            f"color: {c(realized)}; font-size: 15px; font-weight: bold;"
        )

        today = summary.get("today_pnl", 0.0)
        self._card_today._value_lbl.setText(fmt_price(today, prefix=""))
        self._card_today._value_lbl.setStyleSheet(
            f"color: {c(today)}; font-size: 15px; font-weight: bold;"
        )

    def _update_risk_tab(self) -> None:
        try:
            from portfolio.manager import get_portfolio_manager
            risk = get_portfolio_manager().get_risk_analysis()
            if "error" in risk:
                self._risk_content.setText(risk["error"])
                return

            lines = [
                "<b>持仓概况</b>",
                f"持仓数量：{risk['position_count']} 支",
                f"总市值：{fmt_price(risk['total_value'])}",
                "",
                "<b>集中度风险</b>",
                f"最大单股：{risk['max_stock']} ({risk['max_stock_weight']:.1%})"
                + (" ⚠️ 建议分散" if risk["concentration_risk"] else " ✅"),
                f"最大行业：{risk['max_sector']} ({risk['max_sector_weight']:.1%})"
                + (" ⚠️ 行业集中" if risk["sector_risk"] else " ✅"),
                "",
                "<b>1% 风险法则</b>",
                f"建议单笔最大买入：{fmt_price(risk['max_single_buy'])}",
                "",
                "<b>行业分布</b>",
            ]
            for sec, w in sorted(risk["sector_weights"].items(), key=lambda x: -x[1]):
                bar = "█" * max(1, int(w * 20))
                lines.append(f"{sec[:14]:14s}  {w:5.1%}  {bar}")

            self._risk_content.setText("\n".join(lines))
        except Exception as e:
            self._risk_content.setText(f"风险分析计算失败：{e}")

    # ── 交互 ─────────────────────────────────────────────

    def _on_buy(self) -> None:
        from ui.dialogs.trade_dialog import TradeDialog
        dlg = TradeDialog("buy", parent=self)
        if dlg.exec() == TradeDialog.DialogCode.Accepted and dlg.result_data:
            d = dlg.result_data
            try:
                from portfolio.manager import get_portfolio_manager
                get_portfolio_manager().buy(
                    symbol=d["ticker"], shares=d["shares"], price=d["price"],
                    commission=d["commission"], trans_date=d["trans_date"], notes=d["notes"],
                )
                QMessageBox.information(self, "买入成功",
                    f"已记录买入 {d['ticker']} {d['shares']:.3g} 股 @ ${d['price']:.4f}")
            except Exception as e:
                QMessageBox.critical(self, "买入失败", str(e))

    def _on_sell(self, symbol: str = "") -> None:
        from ui.dialogs.trade_dialog import TradeDialog
        dlg = TradeDialog("sell", ticker=symbol, parent=self)
        if dlg.exec() == TradeDialog.DialogCode.Accepted and dlg.result_data:
            d = dlg.result_data
            try:
                from portfolio.manager import get_portfolio_manager
                pnl = get_portfolio_manager().sell(
                    symbol=d["ticker"], shares=d["shares"], price=d["price"],
                    commission=d["commission"], trans_date=d["trans_date"], notes=d["notes"],
                )
                sign = "+" if pnl >= 0 else ""
                QMessageBox.information(self, "卖出成功",
                    f"已记录卖出 {d['ticker']} {d['shares']:.3g} 股 @ ${d['price']:.4f}\n"
                    f"本次实现盈亏：{sign}${pnl:.2f}")
            except Exception as e:
                QMessageBox.critical(self, "卖出失败", str(e))

    def _on_show_detail(self, symbol: str) -> None:
        from core.event_bus import get_event_bus
        get_event_bus().show_ticker_detail.emit(symbol, None)
        get_event_bus().navigate_to.emit("results")

    def _on_context_menu(self, pos) -> None:
        row = self._holdings_table.rowAt(pos.y())
        if row < 0:
            return
        sym_item = self._holdings_table.item(row, 0)
        if not sym_item:
            return
        symbol = sym_item.text()

        menu = QMenu(self)
        buy_act   = menu.addAction(f"📈 追加买入 {symbol}")
        sell_act  = menu.addAction(f"📉 卖出 {symbol}")
        menu.addSeparator()
        detail_act= menu.addAction(f"🔍 个股分析 {symbol}")
        menu.addSeparator()
        del_act   = menu.addAction("🗑 删除持仓记录（纠错）")

        action = menu.exec(self._holdings_table.viewport().mapToGlobal(pos))
        if action == buy_act:
            from ui.dialogs.trade_dialog import TradeDialog
            dlg = TradeDialog("buy", ticker=symbol, parent=self)
            if dlg.exec() == TradeDialog.DialogCode.Accepted and dlg.result_data:
                d = dlg.result_data
                try:
                    from portfolio.manager import get_portfolio_manager
                    get_portfolio_manager().buy(
                        symbol=d["ticker"], shares=d["shares"], price=d["price"],
                        commission=d["commission"], trans_date=d["trans_date"], notes=d["notes"],
                    )
                except Exception as e:
                    QMessageBox.critical(self, "买入失败", str(e))
        elif action == sell_act:
            self._on_sell(symbol)
        elif action == detail_act:
            self._on_show_detail(symbol)
        elif action == del_act:
            pos_data = next((p for p in self._positions if p["symbol"] == symbol), None)
            if pos_data:
                from ui.dialogs.trade_dialog import DeleteConfirmDialog
                dlg = DeleteConfirmDialog(symbol, pos_data["shares"], parent=self)
                if dlg.exec() == DeleteConfirmDialog.DialogCode.Accepted:
                    from portfolio.db import get_db
                    get_db().delete_position(symbol)
                    from core.event_bus import get_event_bus
                    get_event_bus().portfolio_updated.emit()

    def _on_trans_context_menu(self, pos) -> None:
        row = self._trans_table.rowAt(pos.y())
        if row < 0:
            return
        date_item = self._trans_table.item(row, 0)
        sym_item  = self._trans_table.item(row, 1)
        type_item = self._trans_table.item(row, 2)
        if not date_item:
            return

        trans_id   = date_item.data(Qt.ItemDataRole.UserRole)
        trans_date = date_item.text()
        symbol     = sym_item.text() if sym_item else "--"
        trans_type = type_item.text() if type_item else "--"

        menu = QMenu(self)
        del_act = menu.addAction(f"🗑 删除此条记录（{trans_date} {symbol} {trans_type}）")
        action = menu.exec(self._trans_table.viewport().mapToGlobal(pos))

        if action == del_act:
            if trans_id is None:
                QMessageBox.warning(self, "无法删除", "该记录缺少 ID，无法删除。")
                return
            ret = QMessageBox.question(
                self, "确认删除交易记录",
                f"确定删除以下交易记录？\n\n"
                f"日期：{trans_date}\n股票：{symbol}\n类型：{trans_type}\n\n"
                "⚠ 此操作仅删除记录，不会自动调整持仓数量。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                try:
                    from portfolio.db import get_db
                    get_db().delete_transaction(trans_id)
                    from core.event_bus import get_event_bus
                    get_event_bus().portfolio_updated.emit()
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", str(e))

    def _set_cell(self, row: int, col: int, text: str,
                  color: Optional[str], bold: bool = False) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(text)   # 悬停时显示完整内容
        if color:
            item.setForeground(QColor(color))
        if bold:
            f = QFont(); f.setBold(True)
            item.setFont(f)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._holdings_table.setItem(row, col, item)

    def _set_trans_cell(self, row: int, col: int, text: str,
                        color: Optional[str], bold: bool = False) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(text)   # 悬停时显示完整内容
        if color:
            item.setForeground(QColor(color))
        if bold:
            f = QFont(); f.setBold(True)
            item.setFont(f)
        self._trans_table.setItem(row, col, item)

    # ── K 线图 ─────────────────────────────────────────────

    def _on_show_chart(self, symbol: str) -> None:
        """弹出单支股票的 K 线图窗口（5日/日线/周线）"""
        from ui.dialogs.chart_dialog import ChartDialog
        dlg = ChartDialog(symbol, parent=self)
        dlg.show()

    def _on_export_charts(self) -> None:
        """批量导出所有持仓股票的 K 线图 PNG 到本地文件夹"""
        if not self._positions:
            QMessageBox.information(self, "无持仓", "当前没有持仓记录，无法导出图表。")
            return

        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path

        default_dir = str(Path.home() / "Downloads" / "portfolio_charts")
        out_dir = QFileDialog.getExistingDirectory(
            self, "选择导出目录", default_dir
        )
        if not out_dir:
            return

        tickers = [p["symbol"] for p in self._positions]

        # 进度对话框
        progress = QProgressDialog(
            f"正在导出 {len(tickers)} 支持仓股票的 K 线图...", "取消", 0, 100, self
        )
        progress.setWindowTitle("批量导出图表")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        from workers.chart_export_worker import ChartExportWorker
        worker = ChartExportWorker(tickers, Path(out_dir))
        worker.signals.progress.connect(
            lambda pct, msg: (progress.setValue(pct), progress.setLabelText(msg))
        )
        worker.signals.completed.connect(lambda d: self._on_export_charts_done(d, progress))
        worker.signals.error.connect(lambda e: self._on_export_charts_error(e, progress))
        self._export_charts_btn.setEnabled(False)
        QThreadPool.globalInstance().start(worker)

    def _on_export_charts_done(self, out_dir: str, progress: "QProgressDialog") -> None:
        progress.close()
        self._export_charts_btn.setEnabled(True)
        import subprocess, sys
        # 自动打开导出目录
        if sys.platform == "darwin":
            subprocess.Popen(["open", out_dir])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", out_dir])
        else:
            subprocess.Popen(["xdg-open", out_dir])
        QMessageBox.information(
            self, "导出完成",
            f"K 线图已保存到：\n{out_dir}\n\n"
            "文件命名格式：TICKER_5d.png / TICKER_day.png / TICKER_week.png"
        )

    def _on_export_charts_error(self, err: str, progress: "QProgressDialog") -> None:
        progress.close()
        self._export_charts_btn.setEnabled(True)
        QMessageBox.critical(self, "导出失败", f"批量导出图表失败：\n{err}")
