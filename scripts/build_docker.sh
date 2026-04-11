#!/bin/bash
# 构建 RD-Agent 因子发现 Docker 镜像（local_qlib:latest）
# 用法：bash scripts/build_docker.sh
#       bash scripts/build_docker.sh --no-cache   # 强制完整重建

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="local_qlib:latest"
PLATFORM="linux/arm64"   # Apple Silicon；Intel Mac 改为 linux/amd64

echo "========================================"
echo "  构建 QuantByQlib RD-Agent Docker 镜像"
echo "  镜像名：$IMAGE"
echo "  平台：$PLATFORM"
echo "  上下文：$ROOT_DIR"
echo "========================================"

# 检查 Docker 是否运行
if ! docker info &>/dev/null; then
    echo "[ERROR] Docker 未运行，请先启动 Docker Desktop"
    exit 1
fi

# 构建参数
BUILD_ARGS=("--platform" "$PLATFORM" "-t" "$IMAGE" "$ROOT_DIR")
if [[ "$1" == "--no-cache" ]]; then
    BUILD_ARGS=("--no-cache" "${BUILD_ARGS[@]}")
    echo "[INFO] 使用 --no-cache 强制重建"
fi

echo "[INFO] 开始构建（约 5-10 分钟，首次构建较慢）..."
docker build "${BUILD_ARGS[@]}"

echo ""
echo "[INFO] ✅ 镜像构建成功：$IMAGE"
echo "[INFO] 验证："
docker images "$IMAGE"
