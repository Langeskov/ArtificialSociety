# Architecture Notes

## 设计原则

1. **引擎与 I/O 解耦**：`engine/` 是纯 Python 模拟内核，不 import 任何
   FastAPI / SQLite / 网络库，可独立单元测试与回放。
2. **规则优先于智能**：绝大多数 Agent 走确定性规则，LLM 只作为少数高智能
   Agent 的决策源，且其输出必须经过引擎校验（§27）。
3. **社会优先于个体**：用户配置"人口结构"而非单个 Agent；宏观指标是
   一等公民。

## 模块职责

| 模块 | 职责 | 关键文件 |
|---|---|---|
| simulation | 时钟、tick 循环、调度、实验 | clock.py / engine.py |
| agent | Agent 状态容器、人格/意识形态/资源、群体生成 | agent.py / personality.py / ideology.py / resources.py / generator.py |
| society | Society 容器、指标快照、持久 RNG | society.py |
| economy | 收入/消费/税收(按日)/再分配/食物生产 | economy.py |
| politics | 意识形态漂移（惯性/阻尼/锚点/个体化事件响应） | politics.py |
| relationship | 社会网络种子 + 信息传播 | relationship.py / information.py |
| event | 事件 + 生命周期 + 因果链 | event.py / engine.py |
| dynamics | 稳定性层：阻尼/衰减/恢复/反馈/崩溃检测 | dynamics/{stability,damping,decay,recovery,feedback}.py |
| metrics | 宏观指标（Gini / 极化 / 温度 / 多样性 / 同步） | metrics.py |
| models/external | LLM Provider 接口 | provider.py |
| api | REST + WebSocket 门面 | main.py |
| storage | SQLite + JSON 日志 | db.py |

## 单 tick 执行顺序（engine.step，v0.2）

```
for tick in range(n):
    clock.advance(1)
    step_economy(...)            # 收入/食物生产/消费（税收按日征收）
    step_recovery(...)           # 生产乘数向 1.0 恢复
    resolved = decay_events(...) # 事件生命周期衰减 → 返回新解决的事件
    step_events(..., resolved)   # 检测新事件（含恢复型事件）
    propagate_information(...)   # 事件信息沿网络扩散（带延迟）
    step_politics(...)           # 政治更新（惯性+阻尼+锚点+个体化响应）
    maybe_llm_decisions(...)     # LLM（默认关闭）
    decay_memory(...)            # 记忆衰减
metrics = compute_metrics()      # 宏观指标 + 稳定性指标
collapse_detector.update(...)    # 崩溃/边界检测
```

## v0.2 政治更新的力平衡（politics.py）

```
target = position + resource_pressure(个体化)
                   + event_pressure(来自记忆，个体化解读)
                   + social_influence(弱，回音室)
                   + anchor(拉向初始立场，保持多样性)
                   + noise(微小随机波动)
position = spring_damper(position, velocity, target, inertia, damping)
position += center_force(position, center_stability)
```

关键：**税收按日征收**（非逐 tick），修复了 v0.1 财富抽干 → 资源压力 → 单一方向
漂移的塌缩链条。个人锚点强度（0.02）> 社会影响（0.01）> 中心力（0.005），保证
多样性不被社会趋同抹平。

## 数据模型

- **agents**：一次性落库（`snapshot`），运行期在内存；
- **agent_states**：每 20 tick 采样一次，记录 (x,y,z,money,food,anger)，
  支撑"Agent 历史轨迹"和"Trajectory 显示模式"；
- **events + event_links**：`cause_event_id → event_id` 直接构成事件因果图；
- **metrics**：每个 step 落一条，支撑 Dashboard 与多社会比较；
- **events.jsonl**：追加式人类可读事件日志，便于离线回放分析。

## 性能

- 1000 Agent 纯 Python 约 80 ticks/sec；
- 热点在 `step_politics` 的社会影响（已优化为 O(n·degree)，沿关系网络传播）；
- Gini 用 O(n log n)，极化用固定 300 采样，避免 O(n²)。

## 扩展点

- 新增资源：`resources.RESOURCE_KEYS` 增加键即可（经济模块自动读写）；
- 新增意识形态模板：`ideology.IDEOLOGY_TEMPLATES` 加一条；
- 新增事件类型：`event.EVENT_TYPES` 加名 + `event/engine.py` 加检测规则；
- 新 LLM Provider：继承 `models.external.provider.ModelProvider`，实现 `chat`。
