# Political Dynamics Audit (v0.2 → v0.3)

> 项目计划书 v0.3 §2：在修改公式前，完整审计所有直接/间接修改 `agent.x/y/z` 的代码路径。

## 1. 修改路径总览

`engine/politics/politics.py` 是**唯一**直接改写 `ideology.x/y/z` 的模块。其余模块
（economy / event / dynamics）只通过以下方式**间接**影响政治位置：

| 模块 | 间接路径 |
|---|---|
| economy.py | 修改 `resources`（money/food/energy）→ 影响 `_resource_pressure` |
| event/engine.py | 产生事件 → 写入 `agent.recent_events`（经 information.py）→ 影响事件压力 |
| dynamics/decay.py | 衰减 `recent_events` 记忆强度 |
| dynamics/recovery.py | 修改 `production_multiplier` → 影响收入 → 影响资源压力 |
| relationship/information.py | 决定哪些 Agent 知晓事件 |

## 2. 各力源对三轴的影响（v0.2 实际）

| 力源 | X 轴 | Y 轴 | Z 轴 | 时间衰减 | 受 personality | 受资源 | 受社会关系 | 恢复/反作用 |
|---|---|---|---|---|---|---|---|---|
| 资源压力 | **0.4** | 0.2 | 0.3 | 无（随资源变化） | 方向由 trust+authority | 是 | 否 | 锚点/中心力反拉 |
| 事件压力 | salience 最高 0.6 | 0.3~0.6（仅危机） | 0.2~0.6 | 是（记忆衰减） | 方向由 authority/empathy | 否 | 否 | 事件 decay |
| 社会影响（回音室） | 0.01 | 0.01 | 0.01 | 无 | trust 调制 | 否 | 是 | 无 |
| 个人锚点 | 0.02 | 0.02 | 0.02 | 无 | 否 | 否 | 否 | 天然反拉 |
| 中心稳定力 | 0.005 | 0.005 | 0.005 | 无 | 否 | 否 | 否 | 天然反拉 |
| 噪声 | 0.004 | 0.004 | 0.004 | 无 | 否 | 否 | 否 | 无 |

## 3. 根因诊断：为什么退化成"X 轴主导"

1. **X 有持久的独立驱动**：资源压力（`pressure × 0.4`）在**所有 tick** 都存在，
   而 economy 的财富/食物变化持续产生资源压力信号。
2. **Y/Z 只有危机驱动的弱信号**：Y 的事件显著性（protest 0.6、government_response 0.5）
   只在**危机期间**出现；正常时期 Y 的唯一驱动是 `pressure × 0.2`（强度仅为 X 的一半）。
3. **Y/Z 的方向被 personality 锁定**：`(authority − 0.5)×2` 和 `(empathy − 0.5)×2`
   是**固定值**，不随时间演化 → Y/Z 的移动只是 personality 的静态回声。
4. **锚点 + 中心力把 Y/Z 拉向集中区域**：Y/Z 的初始模板（authoritarian y=0.8、
   libertarian y=−0.65）虽分散，但在无独立驱动时，社会影响 + 中心力 + 锚点共同
   把 Y/Z 收敛到均值附近。
5. **结论**：X 是"经济驱动 + 强信号 + 双峰锚点"的完整动力系统；Y/Z 是"无独立驱动 +
   静态方向 + 被中心力抹平"的退化变量。因此长跑后 X 分裂、Y/Z 方差衰减。

## 4. v0.3 修复方向（不伪造噪声）

- 给 **Y 轴**一个**持久的独立驱动**：政府合法性 / 信任动力学（低信任 → 权威轴极化）。
- 给 **Z 轴**一个**持久的独立驱动**：社会联结 / 隔离 / 互助（孤立 → 求集体，联结强 → 个人主义）。
- 引入**弱耦合矩阵**（`C × velocity`），让三轴相互影响但不过度同步。
- 所有力源进入 **Axis Force Registry**，显式标注作用轴 + 强度，输出力分解（可解释）。
