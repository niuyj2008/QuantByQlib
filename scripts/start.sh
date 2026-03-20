#!/bin/bash
# QuantByQlib 启动脚本
# 用法: bash scripts/start.sh

set -e

# 项目根目录（脚本所在目录的上一级）
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Python 解释器：优先用 venv，否则用系统 python3
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/venv/bin/python"
else
    PYTHON="$(which python3)"
fi

echo "Python: $PYTHON ($($PYTHON --version 2>&1))"
echo "WorkDir: $ROOT_DIR"
echo "Starting QuantByQlib..."

exec "$PYTHON" main.py "$@"
