"""
K 线图弹窗
显示单支股票的 5日 / 日线 / 周线 K 线图（mplfinance 渲染，内嵌 matplotlib canvas）
"""
from __future__ import annotations

from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QPushButton, QLabel, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThreadPool, QRunnable, QObject, pyqtSignal


class _FetchSignals(QObject):
    done  = pyqtSignal(object, str)   # (df, period_key)
    error = pyqtSignal(str, str)       # (msg, period_key)


class _FetchWorker(QRunnable):
    """后台拉取 yfinance 数据"""

    _PERIOD_PARAMS = {
        "5d":  dict(period="5d",  interval="5m"),
        "day": dict(period="60d", interval="1d"),
        "week":dict(period="104wk", interval="1wk"),
    }

    def __init__(self, ticker: str, period_key: str, signals: _FetchSignals):
        super().__init__()
        self.ticker     = ticker
        self.period_key = period_key
        self.signals    = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            import yfinance as yf
            params = self._PERIOD_PARAMS[self.period_key]
            df = yf.download(self.ticker, progress=False, auto_adjust=True, **params)
            if df is None or df.empty:
                self.signals.error.emit("无数据", self.period_key)
                return
            # 扁平化多级列（yfinance 新版）
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            df.index.name = "Date"
            self.signals.done.emit(df, self.period_key)
        except Exception as e:
            self.signals.error.emit(str(e), self.period_key)


class _ChartCanvas(QWidget):
    """单个周期的 K 线图 tab 内容"""

    def __init__(self, ticker: str, period_key: str, parent=None):
        super().__init__(parent)
        self.ticker     = ticker
        self.period_key = period_key
        self._loaded    = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._status = QLabel("⏳ 加载中...")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #9299B0; font-size: 13px; padding: 40px;")
        layout.addWidget(self._status)

        self._figure_widget: QWidget | None = None
        self._layout = layout

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        signals = _FetchSignals()
        signals.done.connect(self._on_data)
        signals.error.connect(self._on_error)
        worker = _FetchWorker(self.ticker, self.period_key, signals)
        # signals 需保活
        self._signals = signals
        QThreadPool.globalInstance().start(worker)

    def _on_data(self, df, period_key: str) -> None:
        try:
            import mplfinance as mpf
            import matplotlib
            matplotlib.use("QtAgg")
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            import matplotlib.pyplot as plt

            _TITLES = {"5d": "5日图（5分钟K）", "day": "日线图（近60日）", "week": "周线图（近2年）"}
            title = f"{self.ticker}  {_TITLES.get(period_key, period_key)}"

            style = mpf.make_mpf_style(
                base_mpf_style="charles",
                marketcolors=mpf.make_marketcolors(
                    up="#22C55E", down="#EF4444",
                    edge="inherit", wick="inherit",
                    volume={"up": "#22C55E88", "down": "#EF444488"},
                ),
                figcolor="#FFFFFF",
                gridcolor="#E2E4EA",
                gridstyle="--",
            )

            fig, axes = mpf.plot(
                df,
                type="candle",
                style=style,
                title=title,
                volume=True,
                returnfig=True,
                figsize=(10, 6),
                tight_layout=True,
            )

            canvas = FigureCanvas(fig)
            canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

            self._status.hide()
            self._layout.addWidget(canvas)
            self._figure_widget = canvas
            plt.close(fig)

        except Exception as e:
            self._on_error(str(e), period_key)

    def _on_error(self, msg: str, period_key: str) -> None:
        self._status.setText(f"❌ 加载失败：{msg}")


class ChartDialog(QDialog):
    """
    K 线图弹窗
    三个 tab：5日图 / 日线 / 周线
    """

    def __init__(self, ticker: str, parent=None):
        super().__init__(parent)
        self.ticker = ticker
        self.setWindowTitle(f"📈 {ticker} — K 线图")
        self.resize(900, 580)
        self.setModal(False)   # 非模态，允许继续操作主窗口
        self._setup_ui()
        # 默认加载第一个 tab
        self._canvases["day"].load()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # tab 切换
        self._tabs = QTabWidget()
        self._canvases: dict[str, _ChartCanvas] = {}

        for key, label in [("5d", "📅 5日图"), ("day", "📈 日线"), ("week", "📊 周线")]:
            canvas = _ChartCanvas(self.ticker, key)
            self._canvases[key] = canvas
            self._tabs.addTab(canvas, label)

        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs)

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("btn_secondary")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_tab_changed(self, index: int) -> None:
        key = list(self._canvases.keys())[index]
        self._canvases[key].load()
