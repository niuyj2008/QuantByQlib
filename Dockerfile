# QuantByQlib RD-Agent 因子发现镜像
# 构建：bash scripts/build_docker.sh
# 标签：local_qlib:latest

FROM python:3.9-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 分步安装，方便调试缓存层
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    pandas==2.2.3 \
    scipy==1.13.1 \
    pyarrow \
    requests

RUN pip install --no-cache-dir \
    anthropic \
    openai

RUN git clone --depth=1 https://github.com/microsoft/qlib.git /tmp/qlib && \
    cd /tmp/qlib && \
    pip install --no-cache-dir -e . && \
    rm -rf /tmp/qlib/.git

VOLUME ["/workspace", "/root/.qlib/qlib_data"]

CMD ["python", "/workspace/run_factor_discovery.py"]
