# RD-Agent 因子发现：技术备忘录

> 文档版本：v1.0　　最后更新：2026-02-25　　作者：QuantByQlib 开发组

---

## 目录

1. [RD-Agent 在系统中的定位](#1-rd-agent-在系统中的定位)
2. [架构总览](#2-架构总览)
3. [数据流全链路](#3-数据流全链路)
4. [关键模块说明](#4-关键模块说明)
5. [RD-Agent 与 Qlib 的集成关系](#5-rd-agent-与-qlib-的集成关系)
6. [当前实现状态](#6-当前实现状态)
7. [打通闭环的路线图](#7-打通闭环的路线图)
8. [运行环境与配置](#8-运行环境与配置)
9. [错误处理与降级策略](#9-错误处理与降级策略)

---

## 1. RD-Agent 在系统中的定位

RD-Agent（Research Direction Agent）是 QuantByQlib 的**自动化因子研究引擎**，其核心定位是"AI 量化研究员"：

- 运行在 Docker 容器中，调用 DeepSeek LLM 自主提出因子假设
- 自动对假设进行数学建模、回测验证、性能评估
- 输出 Qlib 兼容的因子表达式及量化指标（IC、Sharpe）
- 为下游的量化选股模型提供潜在的新特征来源

与 Alpha158 等**预定义因子集**的本质区别在于：RD-Agent 产出的是**动态发现的因子**，理论上可以捕获传统因子体系未覆盖的收益来源。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    UI 层（PyQt6）                            │
│  FactorPage                                                  │
│  ├─ 启动 / 停止按钮                                          │
│  ├─ 实时日志面板（绿色终端风格）                              │
│  ├─ 因子发现结果表格（名称 / 表达式 / IC / Sharpe）           │
│  └─ 导出 CSV 按钮                                            │
└────────────────────────┬────────────────────────────────────┘
                         │ Qt 信号
                         ↓
         ┌───────────────────────────────┐
         │  RDAgentWorker（QRunnable）    │
         │  在 QThreadPool 后台线程运行   │
         └───────────────┬───────────────┘
                         ↓
         ┌───────────────────────────────┐
         │  RDAgentRunner                │
         │  ├─ 环境变量装配               │
         │  ├─ Docker 前置检查            │
         │  └─ 日志流式读取线程           │
         └──────────┬────────────────────┘
                    │
        ┌───────────┴────────────┐
        ↓                        ↓
┌──────────────────┐    ┌─────────────────────┐
│  DockerManager   │    │  FactorExtractor     │
│  容器生命周期管理 │    │  日志解析 → 结构化   │
│  日志流读取       │    │  DiscoveredFactor    │
└────────┬─────────┘    └──────────┬──────────┘
         ↓                         ↓
┌──────────────────┐    ┌─────────────────────┐
│  Docker 守护进程  │    │  SessionManager      │
│  RD-Agent 容器   │    │  持久化到 JSON        │
│  rdagent fin_quant│   │  ~/.quantbyqlib/...  │
│  （DeepSeek API）│    └─────────────────────┘
└──────────────────┘
```

---

## 3. 数据流全链路

### 3.1 从启动到因子产出

```
用户点击「启动因子发现」
  ↓
FactorPage._on_start()
  ↓ 创建 RDAgentWorker，投入 QThreadPool
  ↓
RDAgentRunner.start()
  ├─ check_docker()            → Docker Desktop 是否运行
  ├─ image_exists()            → local_qlib:latest 是否存在
  └─ DEEPSEEK_API_KEY 检查     → 必须非空，否则拒绝启动
  ↓
DockerManager.start_container(env_vars, workspace_dir)
  ├─ 删除同名旧容器（若存在）
  ├─ 镜像：local_qlib:latest
  ├─ 平台：linux/amd64（ARM Mac 通过 Rosetta 模拟）
  ├─ Volume：~/.quantbyqlib/rdagent_workspace → /workspace（读写）
  ├─ 网络：host（直接使用宿主机网络）
  └─ 命令：rdagent fin_quant
  ↓
容器运行中：RD-Agent 调用 DeepSeek API 探索因子空间
  ↓
RDAgentRunner._stream_loop()（后台线程）
  ├─ DockerManager.stream_logs() → container.logs(stream=True, follow=True)
  ├─ 每行日志 → signals.log.emit(line)  →  FactorPage 日志面板
  └─ 匹配 "Factor:" 或 "factor_name:" → 追加至 discovered_factors 列表
  ↓
容器退出（正常完成）
  └─ signals.completed.emit(discovered_factors)
       ↓
  FactorPage._on_completed(factors)
       ├─ FactorExtractor 解析原始日志行
       ├─ _populate_factor_table() → 表格展示
       └─ SessionManager.add_session(factors) → JSON 持久化
```

### 3.2 核心数据结构变换

**变换一：原始日志行 → DiscoveredFactor**

```
输入（日志行）：
  "Factor: momentum_5d | Expression: Ref(Close,5)/Close-1 | IC: 0.045 | Sharpe: 1.23"

FactorExtractor 处理：
  1. 5 行滑动窗口匹配（兼容多行输出）
  2. 正则提取 name / expression / ic / sharpe
  3. 按 name 去重

输出（DiscoveredFactor dataclass）：
  name        = "momentum_5d"
  expression  = "Ref(Close,5)/Close-1"
  ic_mean     = 0.045
  ic_std      = None          （若日志未包含则为 None）
  sharpe      = 1.23
  description = ""
  raw_output  = "Factor: momentum_5d | ..."
```

**变换二：DiscoveredFactor → UI 表格**

| 列 | 内容 | 样式 |
|----|------|------|
| 因子名 | factor.name | 粗体 |
| 表达式 | factor.expression | 次要色 |
| IC 均值 | factor.ic_mean | ic > 0.03 绿色；ic < -0.01 红色；其余灰色 |
| Sharpe | factor.sharpe | 居中，2 位小数 |

**变换三：DiscoveredFactor → SessionManager JSON**

```json
{
  "id": 1,
  "timestamp": "2026-02-25T14:30:45",
  "status": "completed",
  "factor_count": 12,
  "factors": [
    {
      "name": "momentum_5d",
      "expression": "Ref(Close,5)/Close-1"
    }
  ]
}
```

存储路径：`~/.quantbyqlib/rdagent_sessions.json`

---

## 4. 关键模块说明

### 4.1 DockerManager（`rdagent_integration/docker_manager.py`）

| 方法 | 说明 |
|------|------|
| `available` | 属性，Docker Desktop 是否连接 |
| `check_docker()` | 返回 `(bool, status_msg)` |
| `image_exists()` | 检查 `local_qlib:latest` 是否存在 |
| `pull_image(progress_cb)` | 流式拉取镜像，进度回调 |
| `start_container(env_vars, workspace_dir)` | 启动容器，返回 `(bool, error_msg)` |
| `stop_container()` | 停止容器 |
| `stream_logs(log_cb, stop_event)` | 实时流式读取日志 |
| `container_status()` | 返回 `"running"` / `"exited"` / `"not_found"` |

**镜像信息：**
- 名称：`local_qlib:latest`（由 `pip install rdagent && rdagent fin_quant` 本地构建）
- 平台：`linux/amd64`（非 DockerHub 公开镜像，需本地生成）

### 4.2 RDAgentRunner（`rdagent_integration/rdagent_runner.py`）

负责编排整个运行流程：

1. `_build_env()` — 从 `.env` 文件读取 API Keys，构造容器环境变量字典
2. `start()` — 前置检查 → 启动容器 → 启动日志流线程
3. `_stream_loop()` — 持续读取日志，实时触发回调，容器退出时调用 `_done_cb`
4. `stop()` — 置位 `_stop_event`，停止日志流，调用 `DockerManager.stop_container()`

### 4.3 FactorExtractor（`rdagent_integration/factor_extractor.py`）

解析引擎，支持三种输出格式：

| 格式 | 示例 |
|------|------|
| 单行日志 | `Factor: xxx \| Expression: ... \| IC: 0.04 \| Sharpe: 1.2` |
| 多行日志 | `factor_name: xxx\nexpression: ...\nic_mean: 0.04` |
| JSON 文件 | `{"factors": [{"name": ..., "expression": ...}]}` |
| Python 模块 | `EXPRESSION = "..."` 变量 |

关键方法：
- `extract_from_lines(lines)` — 解析日志行列表
- `extract_from_file(path)` — 解析 JSON 或 `.py` 文件
- `_try_extract(window)` — 5 行滑动窗口单条解析

### 4.4 RDAgentWorker（`workers/rdagent_worker.py`）

`QRunnable` 子类，作用是：
- 将同步的 `RDAgentRunner` 操作移到 `QThreadPool` 后台线程
- 通过 Qt 信号桥接到主线程 UI 更新
- 发射信号：`log(str)` / `completed(list)` / `error(str)` / `status(str)`

### 4.5 FactorPage（`ui/pages/factor_page.py`）

UI 页面，提供：
- 启动 / 停止控制
- DeepSeek API Key 输入框（可覆盖 `.env` 配置）
- 实时日志滚动显示（绿色终端风格）
- 历史会话列表（可加载历史发现结果）
- 因子表格（支持按 IC、Sharpe 排序）
- 一键导出 CSV

---

## 5. RD-Agent 与 Qlib 的集成关系

### 5.1 当前状态：并行但隔离

```
Qlib 流程（已实现）：
  Alpha158（20 个预定义因子）
       ↓
  LightGBM / LSTM 模型训练
       ↓
  股票评分 → TopK 选股

RD-Agent 流程（已实现）：
  DeepSeek LLM 自动发现因子
       ↓
  DiscoveredFactor（表达式 + IC + Sharpe）
       ↓
  展示 + 导出 CSV        ← 终点（尚未接入 Qlib）
```

两条流程目前相互独立，RD-Agent 发现的因子**尚未反馈到** Qlib 的训练与预测管线。

### 5.2 当前各模块使用的因子来源

| 模块 | 因子来源 | 说明 |
|------|----------|------|
| StockScreener（量化选股） | Alpha158 预定义 20 个因子 | 固定，不含 RD-Agent 因子 |
| StockAnalyzer（个股分析） | Alpha158 预定义 20 个因子 | 固定，不含 RD-Agent 因子 |
| QlibStrategy（所有 5 个策略） | Alpha158 DatasetH | 固定特征集 |
| RD-Agent 发现结果 | N/A | 仅展示，未接入训练 |

### 5.3 因子表达式与 Qlib 的兼容性

RD-Agent 输出的表达式格式直接兼容 Qlib 的 `ExpressionEngine`：

```python
# RD-Agent 输出（直接可用于 Qlib）
"Ref(Close,5)/Close-1"          # 5日动量
"(High-Low)/Close"              # 波动幅度
"Mean(Volume,10)/Volume-1"      # 成交量偏离

# Qlib 使用方式（未实现的集成代码）
from qlib.data import D
df = D.features(
    instruments=['AAPL'],
    fields=["$close", "Ref($close,5)/$close-1"],   # 直接使用表达式
    start_time='2020-01-01'
)
```

---

## 6. 当前实现状态

### 已完成 ✅

- Docker 容器完整生命周期管理（启动/停止/状态查询）
- 环境变量装配与传递
- 容器日志实时流式读取
- 正则解析因子（单行 + 多行 + JSON + Python 模块）
- UI 表格展示（彩色 IC 标注、可排序）
- 因子 CSV 导出
- 历史会话 JSON 持久化
- 完整错误处理与降级策略

### 未完成 ✗

| 缺失功能 | 影响 |
|----------|------|
| 发现因子 → Qlib DatasetH 注入 | 新因子无法参与模型训练 |
| 因子触发模型重训练 | 选股策略无法利用新因子 |
| 因子独立回测验证 | 无法评估单因子贡献度 |
| 因子去重与版本管理 | 跨会话可能出现重复因子 |

---

## 7. 打通闭环的路线图

### Phase A：因子验证（建议优先实现）

在将因子注入 Qlib 之前，需要独立验证：

```python
# 伪代码：因子验证流程
def validate_factor(expression: str, threshold_ic: float = 0.03) -> bool:
    import qlib
    from qlib.data import D

    # 计算因子 IC
    factor_df = D.features(universe, [expression], start, end)
    returns = D.features(universe, ["$close/Ref($close,1)-1"], start, end)
    ic = factor_df.corrwith(returns.shift(-1))  # 滞后一期

    return ic.mean() > threshold_ic
```

### Phase B：因子注入（核心改动）

改动位置：`screening/strategies/qlib_strategy.py`

```python
# 在 QlibStrategy.run() 内加入：
from rdagent_integration.session_manager import get_session_manager

session = get_session_manager().get_latest()
if session and session["factors"]:
    # 筛选通过验证的因子
    valid_factors = [
        f for f in session["factors"]
        if validate_factor(f["expression"])
    ]
    extra_fields = [f["expression"] for f in valid_factors]

    # 扩展 handler fields
    handler_fields.extend(extra_fields)
```

### Phase C：模型重训练

每次有新的通过验证的因子时，触发一次增量重训练：

```python
# 伪代码：增量训练
def retrain_with_new_factors(new_factor_exprs: list[str]):
    dataset = build_dataset(
        fields=ALPHA158_FIELDS + new_factor_exprs
    )
    model = LGBModel(...)
    model.fit(dataset)
    model.save("~/.quantbyqlib/models/lgbm_enhanced.pkl")
```

### Phase D：性能追踪

记录引入新因子前后的选股结果差异，评估 RD-Agent 的实际贡献：

```python
# 因子贡献度评估
before_score = backtest(model_without_new_factors)
after_score  = backtest(model_with_new_factors)
contribution = after_score - before_score  # Sharpe 差值
```

---

## 8. 运行环境与配置

### 8.1 必要条件

| 条件 | 说明 |
|------|------|
| Docker Desktop | 必须运行，版本 ≥ 20.x |
| `local_qlib:latest` 镜像 | 首次通过 `pip install rdagent && rdagent fin_quant` 构建 |
| `DEEPSEEK_API_KEY` | 必填，在 `.env` 中配置 |
| ARM Mac（M 系列） | 自动使用 `linux/amd64` + Rosetta 2，性能略降 |

### 8.2 环境变量

```ini
# .env 文件中配置（均由 RDAgentRunner._build_env() 读取）

# 必填
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 推荐配置（提升因子研究数据质量）
CHAT_MODEL=deepseek/deepseek-chat
FMP_API_KEY=xxxxxxxxxxxxxxxx
ALPHA_VANTAGE_API_KEY=xxxxxxxxxxxxxxxx

# 可选
OPENAI_API_KEY=sk-xxxxxxxx          # 备用 LLM
FINNHUB_API_KEY=xxxxxxxxxxxxxxxx    # 备用新闻数据
```

### 8.3 工作目录挂载

```
宿主机：~/.quantbyqlib/rdagent_workspace/
  ↕ read-write 挂载
容器内：/workspace/

容器在 /workspace 下创建的文件（JSON、Python 模块）
可直接被宿主机 SessionManager 读取。
```

### 8.4 首次初始化步骤

```bash
# Step 1：安装 rdagent pip 包（包含镜像构建工具）
pip3 install rdagent

# Step 2：初次运行（自动构建 local_qlib:latest，约 2GB，需较长时间）
rdagent fin_quant

# Step 3：在 QuantByQlib .env 配置 DEEPSEEK_API_KEY
echo "DEEPSEEK_API_KEY=sk-xxx..." >> ~/.quantbyqlib/.env

# Step 4：启动 QuantByQlib，进入「因子发现」页面点击「启动」
```

---

## 9. 错误处理与降级策略

### 9.1 容器层级

| 错误情况 | 处理方式 |
|----------|----------|
| Docker Desktop 未运行 | `_init_client()` 捕获异常，`available=False`，所有方法返回 False/空 |
| 镜像不存在 | `image_exists()` 返回 False，RDAgentRunner 拒绝启动并提示构建命令 |
| 容器启动失败 | `start_container()` 返回 `(False, error_msg)`，触发 `signals.error` |
| 容器异常退出 | `stream_logs()` 检测到退出，调用 `_done_cb` 传递已收集的部分因子 |

### 9.2 API 层级

| 错误情况 | 处理方式 |
|----------|----------|
| `DEEPSEEK_API_KEY` 未配置 | `_build_env()` 返回 False，启动被拒绝，UI 显示明确错误信息 |
| DeepSeek API 超时 | 由容器内部重试机制处理，日志中会出现重试信息 |
| API 配额耗尽 | 容器报错退出，SessionManager 保存已发现的部分因子 |

### 9.3 解析层级

| 错误情况 | 处理方式 |
|----------|----------|
| 日志格式不符合预期 | `_try_extract()` 返回 None，跳过该行，不影响其他行解析 |
| JSON 文件损坏 | `extract_from_file()` 捕获异常，回退到日志行解析结果 |
| 因子表达式为空 | `DiscoveredFactor` 仍保留，IC/Sharpe 为 None，UI 显示为"—" |

### 9.4 UI 层级

任何错误最终都通过 `signals.error.emit(msg)` 上报给 `FactorPage`，在日志面板以红色文字显示，不会导致应用崩溃。

---

## 附录：关键文件路径速查

| 文件 | 说明 |
|------|------|
| `rdagent_integration/docker_manager.py` | Docker 容器管理，`RDAGENT_IMAGE = "local_qlib:latest"` |
| `rdagent_integration/rdagent_runner.py` | 运行编排，环境变量装配，日志流 |
| `rdagent_integration/factor_extractor.py` | 日志解析，`DiscoveredFactor` 数据类 |
| `workers/rdagent_worker.py` | Qt 线程桥接，`QRunnable` |
| `ui/pages/factor_page.py` | 因子发现 UI 页面 |
| `~/.quantbyqlib/rdagent_sessions.json` | 历史会话持久化 |
| `~/.quantbyqlib/rdagent_workspace/` | 容器工作目录挂载点 |
| `scripts/check_env.py` | 环境预检（含 Docker + 镜像检测） |
