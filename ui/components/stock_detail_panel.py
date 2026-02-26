"""
可复用个股详情面板
复用于：
  ① 选股结果页右侧面板（带 Qlib 模型评分）
  ② 持仓管理页"查看"按钮触发（无模型评分）
  ③ 仪表盘搜索框结果
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QSizePolicy,
    QProgressBar, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThreadPool
from PyQt6.QtGui import QFont

from ui.theme import COLORS


class _SignalBadge(QLabel):
    """彩色信号徽章"""

    STYLES = {
        "bullish": f"background:{COLORS['success']}22; color:{COLORS['success']}; "
                   f"border:1px solid {COLORS['success']}; border-radius:4px; padding:2px 8px;",
        "bearish": f"background:{COLORS['danger']}22; color:{COLORS['danger']}; "
                   f"border:1px solid {COLORS['danger']}; border-radius:4px; padding:2px 8px;",
        "neutral": f"background:{COLORS['text_muted']}22; color:{COLORS['text_secondary']}; "
                   f"border:1px solid {COLORS['text_muted']}; border-radius:4px; padding:2px 8px;",
    }

    def __init__(self, text: str, signal_type: str = "neutral", parent=None):
        super().__init__(text, parent)
        style = self.STYLES.get(signal_type, self.STYLES["neutral"])
        self.setStyleSheet(style)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class _SectionTitle(QLabel):
    """区段标题"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet(f"color:{COLORS['text_primary']}; margin-top:8px;")


class _MetricRow(QWidget):
    """单行指标：标签 + 值 + 信号徽章"""

    def __init__(self, label: str, value_str: str,
                 signal_text: str = "", signal_type: str = "neutral",
                 parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:12px;")
        lbl.setFixedWidth(130)
        row.addWidget(lbl)

        val = QLabel(value_str or "--")
        val.setStyleSheet(f"color:{COLORS['text_primary']}; font-size:12px; font-weight:bold;")
        val.setFixedWidth(100)
        row.addWidget(val)

        if signal_text:
            badge = _SignalBadge(signal_text, signal_type)
            badge.setStyleSheet(
                badge.styleSheet() + " font-size:11px;"
            )
            row.addWidget(badge)

        row.addStretch()


class StockDetailPanel(QWidget):
    """
    可嵌入任意页面的个股分析面板。
    信号：
      add_to_portfolio(ticker) — 记录买入按钮
      run_strategy(ticker)     — 加入回测按钮
    """

    add_to_portfolio = pyqtSignal(str)
    run_strategy     = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_ticker: Optional[str] = None
        self._setup_ui()

    # ── 公开接口 ──────────────────────────────────────────────

    def load(self, ticker: str, quant_score: Optional[float] = None) -> None:
        """
        触发后台分析并加载个股数据
        quant_score: 来自选股模型的评分（0-1），None 表示非选股场景
        """
        ticker = ticker.upper().strip()
        if not ticker:
            return
        self._current_ticker = ticker
        self._quant_score    = quant_score
        self._show_loading(ticker)
        self._start_worker(ticker)

    def clear(self) -> None:
        """清空面板显示空白占位"""
        self._current_ticker = None
        self._show_placeholder()

    # ── UI 初始化 ─────────────────────────────────────────────

    # 状态页索引常量
    _PAGE_PLACEHOLDER = 0
    _PAGE_LOADING     = 1
    _PAGE_CONTENT     = 2
    _PAGE_ERROR       = 3

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 用 QStackedWidget 管理四个互斥状态页，彻底避免叠加显示问题
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack)

        # 0: 占位页（未选中任何股票时显示）
        placeholder = QWidget()
        pl_layout = QVBoxLayout(placeholder)
        pl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl_icon = QLabel("📊")
        pl_icon.setStyleSheet("font-size:48px;")
        pl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl_text = QLabel("点击左侧股票查看个股分析")
        pl_text.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:14px;")
        pl_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl_layout.addWidget(pl_icon)
        pl_layout.addWidget(pl_text)
        self._stack.addWidget(placeholder)   # index 0

        # 1: 加载页
        loading_widget = QWidget()
        ld_layout = QVBoxLayout(loading_widget)
        ld_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label = QLabel("正在分析 ...")
        self._loading_label.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:14px;")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_bar = QProgressBar()
        self._loading_bar.setRange(0, 100)
        self._loading_bar.setValue(0)
        self._loading_bar.setMaximumWidth(300)
        self._loading_status = QLabel("")
        self._loading_status.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
        self._loading_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ld_layout.addWidget(self._loading_label)
        ld_layout.addWidget(self._loading_bar)
        ld_layout.addWidget(self._loading_status)
        self._stack.addWidget(loading_widget)  # index 1

        # 2: 内容区（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setSpacing(6)
        self._content_layout.setContentsMargins(12, 8, 12, 20)
        scroll.setWidget(self._content_widget)
        self._scroll_area = scroll
        self._stack.addWidget(scroll)          # index 2

        # 3: 错误页
        error_widget = QWidget()
        err_layout = QVBoxLayout(error_widget)
        err_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label = QLabel("分析失败")
        self._error_label.setStyleSheet(f"color:{COLORS['danger']}; font-size:14px;")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_layout.addWidget(self._error_label)
        self._stack.addWidget(error_widget)    # index 3

        self._stack.setCurrentIndex(self._PAGE_PLACEHOLDER)

    def _show_placeholder(self) -> None:
        self._stack.setCurrentIndex(self._PAGE_PLACEHOLDER)

    def _show_loading(self, ticker: str) -> None:
        self._loading_label.setText(f"正在分析 {ticker} ...")
        self._loading_bar.setValue(10)
        self._loading_status.setText("初始化中...")
        self._stack.setCurrentIndex(self._PAGE_LOADING)

    def _show_content(self) -> None:
        self._stack.setCurrentIndex(self._PAGE_CONTENT)

    def _show_error(self, msg: str) -> None:
        self._error_label.setText(f"❌ 分析失败：{msg}")
        self._stack.setCurrentIndex(self._PAGE_ERROR)

    # ── Worker 管理 ───────────────────────────────────────────

    def _start_worker(self, ticker: str) -> None:
        from workers.analysis_worker import AnalysisWorker
        worker = AnalysisWorker(ticker)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_progress(self, ticker: str, pct: int, status: str) -> None:
        if ticker != self._current_ticker:
            return
        self._loading_bar.setValue(pct)
        self._loading_status.setText(status)

    def _on_result(self, ticker: str, report) -> None:
        if ticker != self._current_ticker:
            return
        self._render_report(report)
        self._show_content()

    def _on_error(self, ticker: str, msg: str) -> None:
        if ticker != self._current_ticker:
            return
        self._show_error(msg)

    # ── 渲染报告 ──────────────────────────────────────────────

    def _render_report(self, report) -> None:
        """清空旧内容，重新渲染报告所有区块"""
        # 同步清空旧内容（setParent(None) 立即从布局中分离，避免 deleteLater 的异步叠加）
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        # ── 价格头部 ──
        self._render_price_header(report)
        self._add_separator()

        # ── 综合评分 ──
        if report.overall.available:
            self._render_overall_score(report.overall)
            self._add_separator()

        # ── Qlib 模型评分（若来自选股页面）──
        quant_score = getattr(self, "_quant_score", None)
        if quant_score is not None:
            self._render_quant_score(quant_score)
            self._add_separator()

        # ── Alpha158 技术信号 ──
        if report.technical:
            self._render_technical(report.technical)
            self._add_separator()

        # ── 基本面 ──
        if report.fundamental:
            self._render_fundamental(report.fundamental)
            self._add_separator()

        # ── 情绪 ──
        if report.sentiment and report.sentiment.available:
            self._render_sentiment(report.sentiment)
            self._add_separator()

        # ── 操作按钮 ──
        self._render_actions(report.ticker)

        self._content_layout.addStretch()

    def _render_price_header(self, report) -> None:
        """价格 + 涨跌幅标题区"""
        name = report.company_name
        price  = report.current_price
        change = report.change_pct

        title_row = QHBoxLayout()

        name_label = QLabel(f"{name}")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        name_label.setFont(font)
        name_label.setStyleSheet(f"color:{COLORS['text_primary']};")
        name_label.setWordWrap(True)
        title_row.addWidget(name_label, 1)

        ticker_badge = QLabel(report.ticker)
        ticker_badge.setStyleSheet(
            f"background:{COLORS['primary']}33; color:{COLORS['primary']}; "
            f"border:1px solid {COLORS['primary']}; border-radius:4px; "
            f"padding:2px 8px; font-size:11px; font-weight:bold;"
        )
        title_row.addWidget(ticker_badge)

        self._content_layout.addLayout(title_row)

        # 价格行
        if price:
            price_row = QHBoxLayout()
            price_label = QLabel(f"${price:,.2f}")
            font2 = QFont()
            font2.setPointSize(20)
            font2.setBold(True)
            price_label.setFont(font2)
            price_label.setStyleSheet(f"color:{COLORS['text_primary']};")
            price_row.addWidget(price_label)

            if change is not None:
                pct = change * 100
                color = COLORS["success"] if pct >= 0 else COLORS["danger"]
                sign  = "▲" if pct >= 0 else "▼"
                chg_label = QLabel(f"{sign}{abs(pct):.2f}%")
                chg_label.setStyleSheet(f"color:{color}; font-size:16px; font-weight:bold;")
                price_row.addWidget(chg_label)

            price_row.addStretch()
            self._content_layout.addLayout(price_row)
        else:
            no_price = QLabel("暂无实时价格数据")
            no_price.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:12px;")
            self._content_layout.addWidget(no_price)

    def _render_overall_score(self, overall) -> None:
        self._content_layout.addWidget(_SectionTitle("综合评分"))

        row = QHBoxLayout()

        score_label = QLabel(f"{overall.score:.0f}")
        font = QFont()
        font.setPointSize(36)
        font.setBold(True)
        score_label.setFont(font)
        color = (COLORS["success"] if overall.grade_type == "bullish"
                 else COLORS["danger"] if overall.grade_type == "bearish"
                 else COLORS["warning"])
        score_label.setStyleSheet(f"color:{color};")
        row.addWidget(score_label)

        sub_col = QVBoxLayout()
        sub_col.setSpacing(4)

        grade_badge = _SignalBadge(
            f"  {overall.grade}  ",
            overall.grade_type or "neutral"
        )
        font2 = QFont()
        font2.setPointSize(12)
        font2.setBold(True)
        grade_badge.setFont(font2)
        sub_col.addWidget(grade_badge)

        # 分维度进度
        for label, score in [
            ("技术面", overall.tech_score),
            ("基本面", overall.fund_score),
            ("情绪面", overall.senti_score),
        ]:
            if score is None:
                continue
            bar_row = QHBoxLayout()
            bar_lbl = QLabel(label)
            bar_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            bar_lbl.setFixedWidth(42)
            bar_row.addWidget(bar_lbl)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(score * 100))
            bar.setMaximumHeight(8)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background:{COLORS['bg_card']};
                    border-radius:4px;
                    border:none;
                }}
                QProgressBar::chunk {{
                    background:{color};
                    border-radius:4px;
                }}
            """)
            bar_row.addWidget(bar, 1)

            pct_lbl = QLabel(f"{score*100:.0f}")
            pct_lbl.setStyleSheet(f"color:{COLORS['text_muted']}; font-size:11px;")
            pct_lbl.setFixedWidth(28)
            bar_row.addWidget(pct_lbl)

            sub_col.addLayout(bar_row)

        row.addLayout(sub_col, 1)
        self._content_layout.addLayout(row)

    def _render_quant_score(self, score: float) -> None:
        self._content_layout.addWidget(_SectionTitle("Qlib 量化评分"))
        row = _MetricRow(
            "模型综合分数",
            f"{score:.4f}",
            "强势" if score > 0.7 else ("中性" if score > 0.4 else "偏弱"),
            "bullish" if score > 0.7 else ("neutral" if score > 0.4 else "bearish"),
        )
        self._content_layout.addWidget(row)

    def _render_technical(self, tech) -> None:
        self._content_layout.addWidget(_SectionTitle("Alpha158 技术信号"))

        from stock_analysis.alpha_reader import Alpha158Reader
        reader = Alpha158Reader()

        # 调用 get_factor_signals 生成信号列表（若 tech 有 factor_values 属性）
        factor_values = getattr(tech, "factor_values", {})
        if factor_values:
            signals = reader.get_factor_signals(factor_values)
            for sig in signals[:8]:  # 最多显示 8 条
                row = _MetricRow(
                    sig["label"],
                    sig["value_str"],
                    sig["signal_text"],
                    sig["signal_type"],
                )
                self._content_layout.addWidget(row)
        else:
            # 仅显示综合信号
            signal_text = getattr(tech, "signal", "未知")
            stype_map = {"bullish": "bullish", "bearish": "bearish"}
            stype = stype_map.get(signal_text, "neutral")
            row = _MetricRow("综合技术信号", signal_text, signal_text, stype)
            self._content_layout.addWidget(row)

        # 量化综合分
        composite = getattr(tech, "composite_score", None)
        if composite is not None:
            row = _MetricRow(
                "量化综合分",
                f"{composite:.3f}",
                "强势" if composite > 0.65 else ("弱势" if composite < 0.35 else "中性"),
                "bullish" if composite > 0.65 else ("bearish" if composite < 0.35 else "neutral"),
            )
            self._content_layout.addWidget(row)

    def _render_fundamental(self, fund) -> None:
        self._content_layout.addWidget(_SectionTitle("基本面指标（FMP）"))

        from stock_analysis.fundamental import FundamentalAnalyzer
        analyzer = FundamentalAnalyzer()
        signals = analyzer.get_valuation_signals(fund)

        for sig in signals:
            row = _MetricRow(
                sig["label"],
                sig["value_str"],
                sig["signal_text"],
                sig["signal_type"],
            )
            self._content_layout.addWidget(row)

        # 公司概况信息
        if fund.market_cap:
            mc = fund.market_cap
            if mc >= 1e12:
                mc_str = f"${mc/1e12:.2f}T"
            elif mc >= 1e9:
                mc_str = f"${mc/1e9:.2f}B"
            else:
                mc_str = f"${mc/1e6:.0f}M"
            self._content_layout.addWidget(
                _MetricRow("市值", mc_str)
            )

        if fund.analyst_rating and fund.analyst_target:
            stype = "bullish" if "买" in fund.analyst_rating else "neutral"
            self._content_layout.addWidget(
                _MetricRow(
                    "分析师评级",
                    f"目标价 ${fund.analyst_target:.2f}",
                    fund.analyst_rating,
                    stype,
                )
            )

    def _render_sentiment(self, senti) -> None:
        self._content_layout.addWidget(
            _SectionTitle(f"新闻情绪（{senti.model_used or 'VADER'}）")
        )

        if senti.avg_score is not None:
            row = _MetricRow(
                "情绪均值",
                f"{senti.avg_score:+.3f}",
                senti.signal or "中性",
                senti.signal_type or "neutral",
            )
            self._content_layout.addWidget(row)

        stat_row = _MetricRow(
            "正/负/中性",
            f"{senti.positive_count} / {senti.negative_count} / {senti.neutral_count}",
            f"共 {senti.news_count} 条新闻",
            "neutral",
        )
        self._content_layout.addWidget(stat_row)

        # 最新几条新闻标题
        if senti.headlines:
            news_title = QLabel("最新新闻：")
            news_title.setStyleSheet(f"color:{COLORS['text_secondary']}; font-size:11px; margin-top:4px;")
            self._content_layout.addWidget(news_title)

            for i, headline in enumerate(senti.headlines[:5]):
                score = senti.scores[i] if i < len(senti.scores) else 0.0
                color = (COLORS["success"] if score > 0.05
                         else COLORS["danger"] if score < -0.05
                         else COLORS["text_muted"])
                h_label = QLabel(f"• {headline}")
                h_label.setStyleSheet(
                    f"color:{color}; font-size:11px; margin-left:8px;"
                )
                h_label.setWordWrap(True)
                self._content_layout.addWidget(h_label)

    def _render_actions(self, ticker: str) -> None:
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        buy_btn = QPushButton("💼 记录买入")
        buy_btn.setObjectName("btn_primary")
        buy_btn.setMinimumHeight(36)
        buy_btn.clicked.connect(lambda: self.add_to_portfolio.emit(ticker))
        btn_row.addWidget(buy_btn)

        bt_btn = QPushButton("📊 加入回测")
        bt_btn.setObjectName("btn_secondary")
        bt_btn.setMinimumHeight(36)
        bt_btn.clicked.connect(lambda: self.run_strategy.emit(ticker))
        btn_row.addWidget(bt_btn)

        self._content_layout.addLayout(btn_row)

    # ── 工具方法 ──────────────────────────────────────────────

    def _clear_layout(self, layout) -> None:
        """递归清空嵌套布局中的所有 widget"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _add_separator(self) -> None:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{COLORS['border']}; margin:4px 0;")
        self._content_layout.addWidget(sep)
