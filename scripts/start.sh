#!/bin/bash
# QuantByQlib 启动脚本
# 用法: bash scripts/start.sh

set -e

# 项目根目录（脚本所在目录的上一级）
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Python 解释器：按优先级查找装有依赖的环境
# 1. 项目 venv
# 2. 系统 Python 3.9（/usr/bin/python3，依赖已安装于此）
# 3. Homebrew python3.9
# 4. 兜底：系统 python3
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/venv/bin/python"
elif [ -f "/usr/bin/python3" ] && /usr/bin/python3 -c "import loguru" 2>/dev/null; then
    PYTHON="/usr/bin/python3"
elif command -v python3.9 &>/dev/null; then
    PYTHON="$(command -v python3.9)"
else
    PYTHON="$(which python3)"
fi

echo "Python: $PYTHON ($($PYTHON --version 2>&1))"
echo "WorkDir: $ROOT_DIR"
echo "Starting QuantByQlib..."

exec "$PYTHON" main.py "$@"
