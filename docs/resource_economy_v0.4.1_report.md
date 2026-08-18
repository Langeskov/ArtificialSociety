# v0.4.1 Resource & Behavior Layer Report — 资源经济与行为系统

> 回答：**当资源真正约束行为时，社会能否自我维持？**
> 结论：可以，但前提是行为选择必须服从资源预算——本版本最重要的产出不是新模块，
> 而是「效用系统必须满足资源平衡约束」这一校准方法论（见 §3 的失稳案例集）。

## 1. 版本定位

v0.4 建立了社会中间层（Group/Identity/Information/Behavior→Event），但资源仍是
「被读取的状态变量」：每 tick 固定发钱、行为无真实成本、群体资源池是空壳。
v0.4.1 把资源升级为**约束可行动空间**的连续信号，并让经济闭环：

```
work 生产 → 收入/食物 → 代谢消耗 → 压力（连续）→ 行为可行性/效用 → 行为选择 ↺
                     ↘ 交易/分享/群体池（Transaction Layer 守恒转移）↗
```

tick 顺序（`engine/simulation/engine.py`）：

```
economy(代谢+按日税) → recovery → resource_state(连续压力) → deprivation(相对剥夺)
→ events → behavior(Action System) → group_resources(池) → information
→ group(formation/lifecycle) → influence/identity → politics → regions(价格/统计)
```

## 2. 新子系统

| 子系统 | 模块 | 核心机制 |
|---|---|---|
| Resource Security | `engine/economy/security.py` | 四类加权 sigmoid 连续安全度（survival/economic/activity/decision），禁止硬阈值跳变 |
| Transaction Layer | `engine/economy/transaction.py` | reserve/commit/release 三态 + ResourceLedger 流水账（§60–§62） |
| Action System | `engine/behavior/actions.py` `utility.py` | 12 种行为：候选→可行性→效用→softmax 概率选择→成本结算 |
| Group Resource Pool | `engine/group/resources.py` | 成员贡献/贫困分配/资源反馈（池充裕↔凝聚力回路） |
| Regional Economy | `engine/economy/region.py` | 区域禀赋/人口聚合/稀缺定价/局部冲击 |
| Relative Deprivation | `engine/economy/deprivation.py` | 同 region 财富中位数参照的连续剥夺感，不直接改 ideology |
| Economy 重构 | `engine/economy/economy.py` | **取消每 tick 固定收入**（§1），收入只来自 work 行为 |

观测面：Agent snapshot 暴露 `resource_state / current_action / action_utility /
action_feasibility / relative_deprivation / employment`；新增 `GET /api/society/{id}/ledger`
（资源流水账）与 `GET /api/society/{id}/regions`（区域经济）。

## 3. 失稳案例集（本版本的核心教训）

初版 0.4.1 在 300 Agent 长跑中 5 天内全社会崩溃（broke 100% / starve 100%），
且运行时间随 tick 数平方增长。根因不是单点 bug，而是**效用系统与资源预算脱钩**的
系列设计缺陷。每个都已在代码注释中标记：

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | 能量死亡螺旋 | `rest` 效用方向写反（压力越小越休息） | `energy_pressure²` 驱动，枯竭非线性 urgent |
| 2 | 全员慢性饿死 | `work` 效用只看 money_pressure，无视食物危机 | `max(money_pressure, food_pressure)` 强响应 |
| 3 | 流动性死亡（money 500→2） | `save` 每 action 冻结 20% 余额进 illiquid property | 上限 5%/2.0 + money_pressure>0.4 时禁止储蓄 |
| 4 | 社会能量被烧光 | 无不满也可 protest（耗能 5），噪声抗议占 ~8% 行为量 | protest 需 anger≥0.15 或 trust≤0.4（动机门控） |
| 5 | 社交挤占生产 | 能量充足度按 req×2 衰减，贴地板仍满权重 | req×4：能量预算真正约束耗能行为 |
| 6 | 危机中仍社交 | 饥饿 Agent 照常 join/cooperate/communicate | 生存门控：food_pressure>0.5 时非生存行为连续衰减 |
| 7 | 群体池食物黑洞 | share 持续注入池、分配 0.2/tick 几乎不回流 | 池人均存量封顶 + distribution 0.5 + 贫困线 0.5 |
| 8 | membership 爆炸（人均 57 个组） | join_group 无上限；`group_pressure` 效用项被打满，share 永远压过 work | membership 上限 3（§51 有界多身份） |
| 9 | 群体 churn（800 tick 冒出 2268 组） | formation 种子门槛 ≥2 + 退群即再成组永动机 | 种子需 0 归属 + 退群冷却 50 tick + 每 tick 至多 2 组 |
| 10 | 运行时间平方增长 | 死亡群体留在注册表，merge O(A²) 每 tick 全量配对 | `purge_dissolved()` + merge 扫描上限 40 |
| 11 | 性能 61→9.3 ticks/sec | `_actor_id` 的 `str(a)` 默认值提前求值（dataclass `__repr__` 热点）；`_food_price` 每次交易重算全局均值 | 惰性求值；价格每 tick 算一次 |
| 12 | 高税率抽血 | 8%/日税率配套的是旧固定收入模型 | 1%/日（收入仅来自 work 后的再校准） |

教训（§5 精神的推广）：**连续信号负责「多严重」，可行性负责「能不能」，两者都必须
最终反映到行为选择的概率质量上，否则效用系统会系统性地选择社会自杀。**

## 4. 校准后稳态（300 Agent × 30 天，seed 42，默认参数）

| 指标 | day 10 | day 20 | day 30 | 说明 |
|---|---|---|---|---|
| 平均食物 | 41.6 | 23.6 | 24.0 | > critical(20)，耗尽期后回升稳定 |
| 饥饿率 | 5% | 15% | 12% | 修复前 94–100% |
| 平均安全度 | 0.75 | 0.73 | 0.74 | 中等压力（驱动行为多样性，非崩溃） |
| 货币 | 25.3 | 2.1 | 2.1 | 低货币均衡：食物靠工作/分享/贸易，货币稀缺成为常态 |
| 活跃群体 | 147 | 155 | 143 | 有界（修复前无界增长） |
| 群体池存量 | 1023 | 413 | 398 | 有界回流（修复前黑洞） |
| 社会状态 | — | — | RECOVERY | 非永久 CRISIS |

行为分布（day 30，每 tick 300 个选择）：share 53 / rest 41 / cooperate 36 /
leave_group 29 / trade 26 / work ~28 —— 生存行为与社会行为共存，随压力动态切换。

## 5. 性能

| 规模 | v0.4 | v0.4.1 初版 | v0.4.1 修复后 | 备注 |
|---|---|---|---|---|
| 1000 Agent | 61 t/s | **9.3 t/s** | 17.8 t/s | Action System 每 Agent 每 tick 12 行为评估是主要成本 |
| 500 Agent | 149 t/s | 22.4 t/s | 39.7 t/s | |
| 300 Agent 长跑 | 稳定 | **时间平方增长** | 恒定 1.9s/100tick | purge + merge 安全阀消除 |

已做：ledger 惰性 actor_id、价格每 tick 一次、select_action 复用评估（不再对选中行为
二次求值）、per-agent signals 预计算（消除 46 万次/tick 的 personality 字典调用）。
未做（下一步）：utility/feasibility 向量化或按行为静态剪枝；1000 Agent 回到 61+ 需要
NumPy 批处理，与 v0.3 遗留的向量化目标合并。

## 6. 测试

`tests/test_resource_v041.py` 27 个新测试，全套件 62 + 27 = **89 个**。

- Transaction：reserve/commit/release 三态、失败不扣款、转移守恒、ledger 记录
- Security：critical ±2 扫描无跳变（max step < 0.02）、富>穷、pressure 互补
- Actions：硬门槛、protest 动机门控、save 货币门控、leave/join 成员前提、
  membership 上限、概率选择（60 次采样 >1 种行为）、一无所有可选 rest
- Group Pool：存取语义、分配到贫困成员、资源反馈侵蚀/恢复凝聚力
- Deprivation：相对性（参照组）、不改 ideology
- Region：冲击局部化、人口聚合
- 校准验收：300×10 天存活（food > 0.9×critical、starve < 40%、群体有界、性能上限）、
  同种子确定性、无固定收入（关行为后总货币只减不增）

## 7. 配置变更

`configs/default.yaml` / `configs/loader.py` 同步新增：
`resource_security.{critical,scale,weights}`、`actions.*`（深合并覆盖）、
`group_resources.{contribution,distribution}_probability`、`regions.endowments`、
`economy.trade_base_price`；`tax_rate 0.08→0.01`、`food_production 0.12→0.6`（含义从
「每 tick 固定发放」改为「work 行为产出系数」，按 ~15% 工作率覆盖代谢校准）。

## 8. 剩余问题

1. **低货币均衡**：money 稳态 ~2，consume/trade 的货币侧接近冻结。财产（property）
   仍完全非流动——缺「变卖资产」路径， deprivation 高但无法变现。建议下版本加
   `sell_property` 或 consume 允许 property 折算。
2. **群体生态是「小家庭」 regime**：~145 个 3-5 人微型组（min_size=3 + membership≤3
   的数学必然）。与 v0.4 的 4-6 个大组不同。是否上调 merge 激进程度或 min_size，
   留给群体生态专项。
3. **性能未回 v0.4 水平**：17.8 vs 61 ticks/sec @1000。Action System 的成本是结构性的，
   需要向量化（NumPy）才能消化，与 v0.3 遗留目标合并。
4. **Y 轴内生驱动**（v0.3.1 遗留）仍未解决。
5. 前端尚未消费 `resource_security / current_action / regions / ledger` 等新观测面
   （`brief()` 已下发 resource_security/pressure 字段，可做诊断着色）。
