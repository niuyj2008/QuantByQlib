"""运行日志页面"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QComboBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from ui.theme import COLORS


class LogsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_events()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(12)

        # 标题行
        hdr = QHBoxLayout()
        title = QLabel("📋 运行日志")
        title.setObjectName("page_title")
        hdr.addWidget(title)
        hdr.addStretch()

        self._level_filter = QComboBox()
        self._level_filter.addItems(["全部", "INFO", "WARNING", "ERROR"])
        hdr.addWidget(self._level_filter)

        clear_btn = QPushButton("🗑 清除")
        clear_btn.setObjectName("btn_secondary")
        clear_btn.clicked.connect(self._clear)
        hdr.addWidget(clear_btn)

        export_btn = QPushButton("📥 导出")
        export_btn.setObjectName("btn_secondary")
        export_btn.clicked.connect(self._export)
        hdr.addWidget(export_btn)
        layout.addLayout(hdr)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            f"background: #0A0718; color: {COLORS['text_secondary']}; "
            f"font-family: 'Courier New', monospace; font-size: 12px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 8px;"
        )
        layout.addWidget(self._log_view, stretch=1)

    def _connect_events(self) -> None:
        from core.event_bus import get_event_bus
        get_event_bus().log_message.connect(self._append_log)

    def _append_log(self, level: str, message: str) -> None:
        color_map = {
            "INFO":    "#A0E0A0",
            "WARNING": "#F0C060",
            "ERROR":   "#F08080",
            "DEBUG":   "#8090A0",
        }
        color = color_map.get(level, COLORS["text_secondary"])

        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(f"[{level}] {message}\n")

        self._log_view.setTextCursor(cursor)
        self._log_view.ensureCursorVisible()

    def _clear(self) -> None:
        self._log_view.clear()

    def _export(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "quant_log.txt", "文本文件 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._log_view.toPlainText())
