# Artificial Society · Multi-Agent 人工社会模拟

一个**可配置、可观察、可回放的多 Agent 人工社会模拟系统**，核心是三维政治光谱。

> 规则优先于智能，社会优先于个体，观察优先于预设结论。

本项目实现了《Multi-Agent Artificial Society & 3D Political Spectrum v0.1》**第一阶段 MVP 的完整闭环**，并已依次升级至 **v0.2（Stability & Dynamics Patch）** 和 **v0.3（Political Dynamics & Observability）**：

```
参数 → Agent → 行为 → 事件 → 社会变化 → 三维空间 → 可视化 → 可重复实验
```

- v0.2 针对"社会几天内自动塌缩到单一政治边界"的问题，重构了反馈结构（见 `docs/architecture.md`）。
- v0.3 修复了"X 轴两端聚集、Y/Z 基本不动"的一维退化，让三轴各有独立、可解释、弱耦合的驱动力（见 `docs/political_dynamics_audit.md`）。

## 快速开始

```powershell
# 1. 创建虚拟环境（Python 3.11）
cd "D:\Artificial Sociology"
uv venv .venv --python 3.11

# 2. 安装依赖（国内镜像）
uv pip install --python .venv/Scripts/python.exe `
  --index-url https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 3. 启动
.\.venv\Scripts\python.exe run.py

# 4. 浏览器打开
#    http://127.0.0.1:8765
```

点 **CREATE SOCIETY** → 调参数 → **PLAY**，即可看到 1000 个 Agent 在三维政治光谱中演化。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest          # 25 个测试（冒烟 + 稳定性 + 政治动力学）
# 或分套件运行：
.\.venv\Scripts\python.exe -m pytest tests/test_stability.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_political_dynamics.py -v
```

无头冒烟测试覆盖 MVP 闭环（创建 → 生成 → 运行 → 漂移 → 事件 → 指标），
稳定性套件覆盖 v0.2 验收（确定性/正常/危机/个体化响应/长跑），
政治动力学套件覆盖 v0.3 验收（三轴独立/弱耦合/X 主导修复/双峰/多簇/恢复/吸引子多样性/力分解）。

## v0.2 稳定性与动力学（Stability & Dynamics Patch）

修复了 v0.1 的塌缩问题（所有 Agent 数天内撞向 `(x-, y-, z-)` 边界）。根因是
**逐 tick 8% 税收把财富抽干 → 资源压力 → 单一方向政治漂移**。v0.2 重构了反馈结构：

| 机制 | 说明 |
|---|---|
| 政治惯性 + 阻尼（§4, §5） | `velocity = velocity×damping + (target−pos)×(1−inertia)`，立场不再即时跳变 |
| 中心稳定力 + 个人锚点（§6） | 弱稳定力 + 拉向初始立场，保持政治多样性 |
| 个体化事件响应（§8, §9） | 同一事件对不同 Agent 产生不同甚至相反的位移 |
| 事件生命周期（§10, §11） | `trigger→grow→peak→decay→resolved`，事件会自然衰减 |
| 资源恢复（§13, §14, §15） | 食物/能源有生产，抗议只造成临时生产代价 |
| 信息传播延迟（§19, §20） | 事件沿社会网络扩散，非瞬时同步 |
| 社会温度（§17, §18） | 只调节事件概率，不制造硬阈值 |
| 崩溃检测（§26, §27） | 政治方差塌缩 / 边界集中自动告警，不自动重置 |

新增 `engine/dynamics/`（stability / damping / decay / recovery / feedback），
新增稳定性测试套件（`tests/test_stability.py`：确定性、正常/危机、个体化响应、长跑）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_stability.py -v
```

## v0.3 政治动力学与实验观测（Political Dynamics & Observability）

修复了 v0.2 的"X 轴两端聚集、Y/Z 基本不动"的结构性退化（见
`docs/political_dynamics_audit.md`）。v0.3 让 X/Y/Z 三轴都具备独立、可解释、弱耦合的动力学：

| 能力 | 说明 |
|---|---|
| 三轴独立驱动力 | X←经济，Y←政府合法性/信任，Z←社会联结/隔离（非随机噪声） |
| Axis Force Registry | `engine/politics/forces.py` 统一计算力源，逐轴显式标注 |
| 力分解 | 每个 Agent 可展开各力源贡献（经济/权威/社区/事件/社会/锚点/耦合/噪声） |
| 弱轴耦合 | `coupling = C_cross × velocity`，\|c\|<0.05，避免重新同步 |
| X/Y/Z 独立极化度 + 双峰系数 | 直接回答"哪个轴在极化" |
| 轴相关矩阵 + 轴主导检测 | X_DOMINANT / 3D_DYNAMICS 等 |
| 政治簇 + 吸引子检测 | 贪心密度聚类 + 平均速度判定 |
| 2D 投影 + 分布直方图 | XY/XZ/YZ 投影、X/Y/Z 直方图 |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_political_dynamics.py -v
.\.venv\Scripts\python.exe scripts\longrun_report.py   # 长跑报告
```

## v0.3.1 政治动力学校准（Political Dynamics Calibration）

修复了 v0.3 长跑稳定复现的三类动力学异常（见 `docs/v0.3.1_calibration_report.md`）：

| 异常 | 根因 | v0.3.1 修复 |
|---|---|---|
| X 轴双峰/两极 | `econ_dir = -1 if gov≥0.5 else +1` 二值分类器 | 连续 `econ_bias = tanh((0.5−gov)·sensitivity)` + deadzone + saturation |
| Z 轴永久 Z+ 漂移 | `(1−isolation)·0.5` 恒正，联结→Z+ | 双向偏好 `autonomy_pref − belonging_need` + group_pressure |
| Y 轴弱动力 | 仅 trust_in_government 驱动，强度 0.03 | 多驱动：legitimacy + security(冲突) + institutional(制度绩效) |

新增：力预算（人口级各来源占比）、轴漂移/方差/均值三指标、六方向边界集中、
分布形态分类、force/velocity 主导轴检测、`/api/society/{id}/dynamics*` 端点。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_political_calibration.py -v   # 12 个校准测试
.\.venv\Scripts\python.exe scripts\calibrate.py --days 100 --seeds 3          # 校准矩阵
```

## v0.4 涌现社会（Emergent Society：Group + Identity + Information）

从「多 Agent 模拟器」升级为「人工社会实验平台」：首次实现 **Agent → Relationship →
Group → Identity → Information → Behavior → Event → Political Change** 的社会中间层闭环
（见 `docs/emergent_society_v0.4_report.md`）。

| 子系统 | 核心机制 |
|---|---|
| **Group**（`engine/group/`） | 5 因子 formation_score 涌现成组（非配置生成）、合并/分裂/解散生命周期 |
| **Identity**（`engine/identity/`） | 社会身份（≠ ideology），belonging/autonomy 成为 Z 轴上游 |
| **Information**（`engine/information/`） | Event/Information/Belief 三层分离、失真、谣言、级联、回音室 |
| **Behavior→Event**（`engine/behavior/`） | 行为反向产生事件（work/trade/protest/conflict/migrate） |

关键原则：`ideology ≠ group`、`personality ≠ identity`、`event ≠ belief`（§1 严禁概念混淆）。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_groups.py tests/test_identity.py tests/test_information.py tests/test_social_emergence.py -v
.\.venv\Scripts\python.exe scripts\ablate.py --agents 300 --days 30 --seeds 3   # 消融实验
```

## 系统架构（六层）

```
┌────────────────────────────────────┐
│      Visualization Layer (web)     │  3D 政治光谱 / 事件时间线 / 指标仪表盘
├────────────────────────────────────┤
│        Simulation Engine           │  时间 / 事件 / 关系 / AI 调度
├────────────────────────────────────┤
│           Agent Layer              │  人格 / 意识形态 / 资源 / 记忆 / 目标
├────────────────────────────────────┤
│          Social Model              │  经济 / 政治 / 群体 / 冲突 / 合作
├────────────────────────────────────┤
│           Data Layer               │  SQLite + JSON Event Log
├────────────────────────────────────┤
│      External Model API            │  OpenAI 兼容 / Ollama / 本地 LLM
└────────────────────────────────────┘
```

## 目录结构

```
artificial-society/
├── engine/                # 纯 Python 模拟内核（无 I/O，可单测）
│   ├── simulation/        #   时钟 clock.py + 引擎 engine.py
│   ├── agent/             #   Agent / 人格 / 意识形态 / 资源 / 群体生成器
│   ├── society/           #   Society 容器
│   ├── economy/           #   资源动力学（收入/消费/税收/再分配）
│   ├── politics/          #   政治漂移（forces 力注册表 + observability 观测）
│   ├── relationship/      #   社会网络 + 信息传播
│   ├── event/             #   事件 + 因果链
│   └── metrics/           #   宏观指标（基尼/极化/熵/稳定度/轴主导）
├── models/external/       # Model Provider 统一接口（LLM 钩子）
├── api/main.py            # FastAPI：REST + WebSocket
├── storage/db.py          # SQLite + JSON 事件日志
├── visualization/static/  # 前端（无 CDN 依赖，Canvas 2D 自绘 3D）
├── configs/               # 默认配置 + YAML 加载
├── experiments/           # 实验配置归档
├── scripts/               # 长跑报告等分析脚本
├── data/                  # 运行时数据（SQLite / events.jsonl）
└── docs/                  # 文档（架构 / 政治动力学审计 / v0.3 说明）
```

## 核心概念

### 三维政治光谱（§7）

| 轴 | 含义 | 正方向 | 负方向 |
|---|---|---|---|
| X | 经济 / 分配 | Economic Freedom | Economic Control |
| Y | 社会 / 权威 | Authority | Liberty |
| Z | 个体 / 集体 | Individualism | Collectivism |

坐标 ∈ [-1, +1]。"主义"（Liberal / Conservative / Socialist / Libertarian /
Authoritarian / Communitarian / Anarchist / Centrist）**只是生成 Agent 的初始模板**，
不是固定标签——Agent 的真实坐标会随资源变化、社会互动、事件等持续漂移（§8）。

### Agent 模型（§4–§6）

- **人格**：10 个维度（Openness / Conscientiousness / … / Authority），与政治立场解耦；
- **资源**：money / food / energy / property / influence / information；
- **分层智能**：默认 90% 规则 + 9% 统计 + 1% LLM（§26），计算成本可控；
- **群体配置**：用户设置的是"人口结构"（意识形态比例 / 人格分布），而非逐个 Agent。

### 事件因果链（§16）

事件之间通过 `event_links` 记录 `cause → effect`，可展开为：

```
food_shortage → anger↑ → protest → government_response → …
```

前端"Event Chain"标签页和点击事件后的链式视图，用于观察"微小事件如何演化为宏观社会变化"。

## API（最小集合，§30）

```
POST /api/society/create               创建 Society
POST /api/society/{id}/start|pause|resume|step|reset|speed
GET  /api/society/{id}                 Society 状态
GET  /api/society/{id}/agents|groups|events|metrics|trajectory
GET  /api/society/{id}/politics                政治状态空间（极化/相关/轴主导/簇）
GET  /api/society/{id}/politics/distribution   X/Y/Z 分布直方图
GET  /api/society/{id}/politics/clusters       政治簇检测
GET  /api/society/{id}/politics/correlation    轴相关矩阵
GET  /api/society/{id}/politics/attractors     吸引子检测
GET  /api/agent/{id}                           单 Agent 详情（含力分解）
GET  /api/agent/{id}/history                   单 Agent 历史轨迹
GET  /api/agent/{id}/relationships             社会关系
POST /api/model/chat                           外部 LLM 统一入口
POST /api/experiment/create|run                多 Society 实验
GET  /api/experiment/{id}
WS   /ws/simulation/{id}                       实时推送（tick / event / metric_update）
```

## 接入外部 LLM（§25–§27）

在左侧面板把 Provider 从 `rule_based` 切到 `ollama`，填写 Base URL
（默认 `http://127.0.0.1:11434/v1`）。高智能 Agent 会请求结构化决策
（`{action, target, amount, reason, confidence}`），引擎**先校验再执行**，
避免模型直接破坏模拟规则。

## 可调整参数（§34）

时间倍率 · Society 数 · Agent 数 · 初始资源 · 资源再生 · 意识形态分布 ·
人格分布 · 随机种子 · 模拟时长 · 事件频率 · 政治运动强度 · 社会影响强度 ·
LLM 使用比例 · Model Provider · Model Name

## 阶段路线（§41）

| Phase | 内容 | 状态 |
|---|---|---|
| 1 | Simulation Core | ✅ |
| 2 | Agent + Personality + Resources | ✅ |
| 3 | 3D Political Spectrum | ✅ |
| 4 | Event System + Event Chain | ✅ |
| 5 | Web Visualization | ✅ |
| 6 | External Model API | ✅ |
| 7 | Multi-Society Experiment | ✅ |
| 8 | Advanced Social Dynamics | 🔜 第二阶段（群体/政党/选举/贸易/冲突） |

## 技术说明

- **零前端依赖**：3D 散点图用 Canvas 2D 手写透视投影 + 轨道控制器（旋转/缩放/平移/点选），
  不依赖 CDN，离线可用；
- **后端**：FastAPI + uvicorn（含 websockets），SQLite（stdlib）+ JSON 事件日志；
- **性能**：1000 Agent 约 **61 ticks/sec**（500 Agent 约 149 ticks/sec，纯 Python，未向量化），
  Agent 状态每 20 tick 采样一次入库存历史；
- **存储**：`data/society.sqlite3`（结构化）+ `data/events.jsonl`（追加事件日志）。

## 启动方式（三种）

```powershell
# 方式一：默认启动（端口 8765）
.\.venv\Scripts\python.exe run.py

# 方式二：指定端口
.\.venv\Scripts\python.exe run.py --port 9000

# 方式三：直接跑分析脚本（无需起 Web 服务）
.\.venv\Scripts\python.exe scripts\longrun_report.py   # 长跑报告
.\.venv\Scripts\python.exe -m pytest                   # 跑全部测试
```

启动后浏览器打开 http://127.0.0.1:8765 ：**CREATE SOCIETY** → 调参 → **PLAY**。

## 内部构建（关键模块）

| 层 | 模块 | 职责 |
|---|---|---|
| 模拟内核 | `engine/simulation/engine.py` | 主循环编排（economy → recovery → event → info → politics → metrics） |
| 政治动力学 | `engine/politics/forces.py` | Axis Force Registry：三轴独立驱动力 + 力分解 |
| 政治观测 | `engine/politics/observability.py` | 极化度/相关矩阵/轴主导/簇/吸引子 |
| 政治更新 | `engine/politics/politics.py` | 弹簧-阻尼动力学（惯性 + 阻尼 + 极端化代价） |
| 经济 | `engine/economy/economy.py` | 收入/消费/按日税收/再分配/资源恢复 |
| 关系网络 | `engine/relationship/` | 社会网络 + 信息传播延迟 |
| 指标 | `engine/metrics/metrics.py` | 社会温度/基尼/极化/稳定度/轴主导 |
| 接入层 | `api/main.py` | FastAPI REST + WebSocket |
| 前端 | `visualization/static/` | Canvas 2D 自绘 3D 光谱 + 2D 投影 + 直方图 |

引擎与 I/O 解耦：`engine/` 不 import FastAPI/SQLite/网络库，可独立单测与回放。

## 当前问题和已知限制

1. **性能未达目标**：v0.3 引入三轴力分解 + 观测指标后，1000 Agent 从 v0.2 的 ~67
   ticks/sec 降到 46，本轮优化回补到 **61**，仍未达到计划书 ~80 的目标。
   瓶颈在 `compute_forces` 的社会影响循环（O(n×degree) 的逐邻居距离计算）和
   逐 Agent 的标量算术，尚未向量化。
2. **长跑验收是缩水版**：计划书 §50 要求 1000 Agent × 1000 天 × 10 Society，
   在纯 Python 下约需 5–10 小时；当前验证跑的是 1000 × 30 天 × 10（
   `scripts/longrun_report.py` 的 `DAYS` 可调）。结论方向可信，但未完成完整 1000 天。
3. **社会影响是静态网络**：关系网络在初始化后不再演化，信息传播/回音室基于固定拓扑；
   群体形成、就业、贸易、政党等高级社会动力学（计划书 Phase 8）尚未实现。

## 下一步优化

1. **性能（优先级最高）**：用 NumPy 批量向量化 `compute_forces`（把三轴力计算改成
   数组运算），或把社会影响改为稀疏矩阵乘，目标回到 ~80+ ticks/sec；同时缓存邻居
   Agent 对象引用，去掉社会循环里的 `agent_map.get(nid)`。
2. **动态社会网络**：实现群体形成/加入/退出、就业、贸易、政党，让 Z 轴（集体↔个体）
   与 Y 轴（权威↔自由）拥有更丰富的内生驱动。
3. **实验工具链**：参数敏感性分析、蒙特卡洛多种子扫描、轨迹回放对比，完善
   `experiments/` 目录。
