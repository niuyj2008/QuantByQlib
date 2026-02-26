"""
QuantByQlib 应用入口
美股量化辅助决策平台
"""
import sys
import os
from pathlib import Path

# ── 确保项目根目录在 Python 路径中 ──────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 加载 .env 环境变量（API Keys 等）────────────────────────
def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            # 手动解析
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

# ── 初始化日志系统 ───────────────────────────────────────────
from utils.logger import setup_logger, logger
setup_logger()

# ── 启动 Qt 应用 ─────────────────────────────────────────────
def main() -> int:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon

    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("QuantByQlib")
    app.setApplicationDisplayName("QuantByQlib — 美股量化辅助决策平台")
    app.setOrganizationName("QuantByQlib")

    # ── 应用全局样式表 ──────────────────────────────────────
    from ui.theme import get_stylesheet
    app.setStyleSheet(get_stylesheet())

    # ── 初始化事件总线（QObject 必须在 QApplication 之后创建）
    from core.event_bus import get_event_bus
    bus = get_event_bus()

    # ── 确保数据目录存在 ────────────────────────────────────
    data_dir = Path.home() / ".quantbyqlib"
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (data_dir / "rdagent_output").mkdir(parents=True, exist_ok=True)

    # ── 创建并显示主窗口 ─────────────────────────────────────
    from ui.main_window import MainWindow
    from PyQt6.QtCore import QTimer
    window = MainWindow()
    window.show()

    # ── 检测 Qlib 初始化状态（延迟到事件循环后，确保主窗口信号连接就绪）
    QTimer.singleShot(50, lambda: _check_qlib_init(bus))

    logger.info("QuantByQlib 启动完成")
    bus.status_message.emit("QuantByQlib 已就绪")

    return app.exec()


def _check_qlib_init(bus) -> None:
    """检测 Qlib 数据是否已初始化，并更新全局状态"""
    from core.app_state import get_state
    state = get_state()

    qlib_data = Path.home() / ".qlib" / "qlib_data" / "us_data"
    if qlib_data.exists() and any(qlib_data.iterdir()):
        try:
            import qlib
            from qlib.constant import REG_US
            qlib.init(provider_uri=str(qlib_data), region=REG_US)
            state.qlib_initialized = True
            state.qlib_data_path = str(qlib_data)
            logger.info(f"Qlib 初始化成功：{qlib_data}")
            bus.qlib_initialized.emit()
        except Exception as e:
            logger.warning(f"Qlib 初始化失败：{e}")
            state.qlib_initialized = False
    else:
        logger.info("Qlib 数据未找到，请前往「参数配置」下载数据")
        state.qlib_initialized = False


if __name__ == "__main__":
    sys.exit(main())
