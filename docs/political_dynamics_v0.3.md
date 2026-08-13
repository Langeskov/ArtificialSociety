# Political Dynamics v0.3 — 三维状态空间重构

> 项目计划书 v0.3：Political Dynamics & Experimental Observability。

## 1. 问题诊断

v0.2 长跑暴露出结构性偏差：**X 轴逐渐向两端分裂，Y 基本不变，Z 弱变化**，
系统从三维动力系统退化成主要沿 X 轴运动的一维极化系统。

审计（`docs/political_dynamics_audit.md`）定位到根因：

| 力源 | X | Y | Z | 结论 |
|---|---|---|---|---|
| 资源压力 | **0.4** | 0.2 | 0.3 | X 有持久独立驱动 |
| 事件压力 | 高显著性 | 仅危机期 | 仅危机期 | Y/Z 无日常驱动 |
| 方向来源 | 固定 | 固定 personality | 固定 personality | Y/Z 方向被锁定 |
| 锚点+中心力 | — | 拉向集中区 | 拉向集中区 | Y/Z 被抹平 |

**结论**：X 是"经济驱动 + 强信号 + 双峰锚点"的完整动力系统；Y/Z 是"无独立驱动
+ 静态方向 + 被中心力抹平"的退化变量。

## 2. v0.3 修复

### 三轴独立驱动力（§9）

| 轴 | 主要驱动 | 机制 |
|---|---|---|
| X（经济/分配） | 资源稀缺、财富、税收 | 稀缺 → 亲政府求管控（x-），反政府求自由（x+） |
| Y（社会/权威） | 政府合法性、信任 | 低信任 → 权威轴极化（亲权威更权威、反权威更自由） |
| Z（个体/集体） | 社会联结、隔离、互助 | 联结良好 → 个人主义（z+），孤立+高同理心 → 集体主义（z-） |

Y/Z 现在拥有**持久的独立驱动**，而非危机期才出现的弱信号。

### 弱轴耦合（§7, §8）

```
coupling_force = C_cross × velocity，|c| < 0.05
```

耦合受 personality（开放性）非线性调制，交叉项保持低值，避免三轴重新同步。

### 力分解（Axis Force Registry，§4, §5）

所有力源统一经 `engine/politics/forces.py::compute_forces` 计算，每个力源显式标注
作用轴。每个 Agent 保存最近一次力分解（`last_forces`），Inspector 可展开：
经济 / 权威 / 社区 / 事件 / 社会 / 锚点 / 中心 / 耦合 / 噪声 的逐轴贡献。

## 3. 观测能力（§12–§22）

| 能力 | 实现 |
|---|---|
| X/Y/Z 独立极化度 + 双峰系数 | `observability.polarization_per_axis` |
| 轴相关矩阵 | `observability.axis_correlation` |
| 轴主导检测（X_DOMINANT / 3D_DYNAMICS / …） | `observability.detect_axis_dominance` |
| 政治簇检测 | `observability.detect_clusters`（贪心密度聚类） |
| 吸引子检测 | `observability.detect_attractors`（簇 + 平均速度） |
| 分布直方图 | `observability.distribution_histogram` |

这些指标通过 `/api/society/{id}/politics*` 暴露，前端提供 2D 投影（XY/XZ/YZ）、
直方图、政治簇、力分解、轴主导标签。

## 4. 禁止的假修复（§47）

- 禁止随机给 Y/Z 加噪声伪造运动
- 禁止强制三轴等方差
- 禁止检测到 X 极化后直接压制 X
- 禁止拉回三维中心或固定漂移

所有三维变化来自可解释机制（Agent/Personality/Resources/Events/Relationships/
Groups/Memory/Coupling）。

## 5. 测试

- `tests/test_political_dynamics.py`：三轴独立、弱耦合、X 主导修复、双峰、
  多簇、恢复、吸引子多样性、力分解。
- 长跑报告：`scripts/longrun_report.py`（10 Society × 1000 Agent × N 天）。

## 6. 确定性修复

v0.2 的 `propagate_information` 迭代 `set`（`knowers`），其迭代顺序依赖进程级
`PYTHONHASHSEED`，导致跨进程不可复现。v0.3 改为 `sorted(knowers)`，保证确定性。
