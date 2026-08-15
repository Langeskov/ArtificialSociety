# v0.4 Emergent Society Report — Group + Identity + Information

> 计划书 v0.4 §83。回答：**当 Agent 拥有关系、群体、身份和不同信息时，社会是否会自己产生结构？**

## 1. 版本定位与闭环

v0.3.1 解决了「政治空间会不会被人为公式推到某个方向」；v0.4 的问题变为
「Agent → Relationship → Group → Identity → Information → Behavior → Event →
Political Change → Social Reorganization ↺」这个社会中间层是否会自然涌现。

实现的新社会闭环（`engine/simulation/engine.py` tick 顺序）：

```
economy → recovery → event → behavior(§40) → information(§25) → group(§5)
        → influence/identity(§20/§16) → politics(§3) → memory → social_state(§54)
```

## 2. 验收清单（§82）

| 要求 | 状态 | 证据 |
|---|---|---|
| Group 能自然形成 | ✅ | 300 Agent / 5000 tick → 4-6 个群体自然涌现 |
| Group 能自然解散 | ✅ | `GROUP_DISSOLVED` 事件 + test_group_dissolves |
| 多身份 | ✅ | test_multiple_group_membership |
| Identity ≠ ideology | ✅ | test_identity_is_independent_from_ideology |
| Group ≠ political cluster | ✅ | test_group_has_internal_diversity |
| Event 与 Information 分离 | ✅ | test_event_information_belief_are_distinct |
| Information 局部传播 | ✅ | frontier 传播 + test_information_propagation |
| 不同 belief | ✅ | test_confirmation_bias（openness 调制） |
| Information 影响 behavior | ✅ | test_information_changes_belief |
| Behavior 产生 Event | ✅ | test_behavior_creates_event |
| Group 反影响成员 | ✅ | apply_group_influence（身份强化 + 锚点牵引） |
| 群体间合作/竞争 | ✅ | inter-group conflict + merge |
| 政治位置仍由 v0.3.1 更新 | ✅ | 37 个 v0.3.1 测试仍通过 |
| 无 preset 时自然涌现 | ✅ | test_emergence_without_preset_groups |
| 不同 seed 不同结构 | ✅ | test_different_seeds_produce_different_structures |

## 3. 核心设计决策

1. **Group 由行为涌现，不由配置生成**（§5）：formation_score = 五因子的几何平均
   （§7 归一化），需连续 `persistence_ticks` 满足才成组（§8），`min_size` 门槛（§9）。
2. **Identity 是独立变量**（§14）：`Identity` 只含 social 字段，绝不写入 x/y/z；
   它通过 `autonomy/belonging` 成为 Z 轴上游（§15），政治位置仍由 v0.3.1 动力学更新。
3. **Event/Information/Belief 三层分离**（§26）：Event 客观、Information 传播中
   失真、Belief 主观；信念更新受 confirmation bias（openness 调制，§35）。
4. **反向闭环**（§40）：rule-based 行为 → 聚合 → 宏观事件。
5. **性能**（§69）：formation 只沿关系网络邻域计算（O(N·degree)），信息传播用
   frontier 集合（每个接收者只传播一次），避免 O(N²)。

## 4. 社会涌现观测（300 Agent × 5000 tick, seed 42）

| 指标 | 值 |
|---|---|
| 群体数量 | 4-6 |
| 平均群体规模 | ~52（含 6-89 不等） |
| 群体凝聚力 | 0.72-0.88 |
| 身份强度（有群体者） | ~0.70 |
| 归属感 / 自主性 | 向 0.65 / 0.35 目标收敛（不锁死） |
| 信息消息数 | 10-14 |
| 生命周期事件 | GROUP_FORMED × N, GROUP_MERGED, GROUP_DISSOLVED |

## 5. 消融对比（§66, §67）

`scripts/ablate.py`（300 Agent × 30 天 × 3 seeds）：

| Scenario | Groups | AvgSize | Identity | Frag | Integ | Info | X Pol |
|---|---|---|---|---|---|---|---|
| baseline | 5.0 | 43.9 | 0.49 | 0.38 | 0.37 | 146 | 0.77 |
| no_groups | 0.0 | 0.0 | 0.00 | 0.00 | 1.00 | 123 | 0.89 |
| no_identity | 5.0 | 44.3 | 0.00 | 0.38 | 0.36 | 148 | 0.78 |
| no_information | 4.3 | 55.7 | 0.53 | 0.44 | 0.46 | 0 | **1.04** |
| no_behavior | 5.0 | 43.9 | 0.49 | 0.38 | 0.37 | 12 | 0.80 |
| null（全关） | 0.0 | 0.0 | 0.00 | 0.00 | 1.00 | 0 | 0.92 |

**回答 §83 的核心问题——新机制确实产生了新的宏观结构：**

1. **Group 产生碎片化**：baseline 的 fragmentation=0.38 vs no_groups/null 的 0.00
   —— 群体是社会碎片化的来源，没有群体就没有碎片化。
2. **Information 降低政治极化**：no_information 的 X 极化 1.04 > baseline 0.77
   —— 信息共享让政治极化「软化」，切断信息后极化反而加剧。这是最有价值的涌现发现。
3. **Identity 提供归属**：baseline 的 identity_strength=0.49，no_groups/null 为 0
   —— 群体成员形成了社会身份。
4. **Group 略缓极化**：no_groups 的 X 极化 0.89 > baseline 0.77 —— 群体内部的政治
   互动对极端化有微弱抑制作用。

## 6. 测试

`python -m pytest` → **62 passed**（37 旧 + 25 新）。

新增：`test_groups.py`（6）、`test_identity.py`（5）、`test_information.py`（8）、
`test_social_emergence.py`（6）。

## 7. 剩余问题

1. **Y 轴仍依赖 anchor**（v0.3.1 遗留）：群体/身份机制未直接解决 Y 的内生驱动。
2. **Group 分类**（§13）：第一版 `type=emergent`，未做 family/profession/political 分类。
3. **群体资源池**（§49）仅建模（`Group.resources`），未实现存/取/共享的财务逻辑。
4. **LLM 仍 OFF**（§68）：observer/analyst 角色未接入。
5. **长跑缩水**：计划书 1000×1000×10 需数十小时，本次用 300×50×3 演示（`scripts/ablate.py` 可调）。
