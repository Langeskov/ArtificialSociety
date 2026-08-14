# Political Dynamics Audit — v0.3 → v0.3.1 Calibration

> 项目计划书 v0.3.1 §2：在修改公式前，完整审计所有产生 fx/fy/fz 的代码路径。

审计范围：`engine/politics/forces.py`（唯一改写 ideology 的力计算）、
`engine/politics/politics.py`（更新循环）、`engine/politics/observability.py`、
`engine/metrics/metrics.py`、`configs/default.yaml` / `configs/loader.py`。

## 1. 力来源总表

| 力来源 | 作用轴 | 当前公式 | 默认强度 | 长期存在? | 双向? | 受个体差异? | 持续偏置? |
|---|---|---|---|---|---|---|---|
| economic (X) | X | `pressure * 0.4 * (-1 if gov≥0.5 else +1) * wx` | 0.4 | ✅ 每 tick | ❌ 二值 | ❌ 二值 gov | ❌ **二值分叉** |
| authority (Y) | Y | `(0.5−trust_gov) * (authority−0.5)*2 * 0.03 * wy` | 0.03 | ⚠️ 仅信任驱动 | ✅ | ✅ authority | ⚠️ 偏弱 |
| community (Z) | Z | `((1−isolation)*0.5 − isolation*empathy) * 0.02 * wz` | 0.02 | ✅ 每 tick | ❌ | ✅ empathy | ❌ **永久 Z+** |
| event (X/Y/Z) | 三轴 | `salience * direction(personality) * reactivity` | 事件相关 | 危机期 | X 二值 | ✅ | ❌ **X 二值 / Z 硬映射** |
| social | 三轴 | 加权邻居均值 − 自身，× influence_strength | 0.01 | ✅ | ✅ | ⚠️ trust 调制 | ✅ 无 |
| anchor | 三轴 | `(anchor − pos) * 0.02` | 0.02 | ✅ | ✅ | ❌ 无 | ⚠️ 拉回初始 |
| center | 三轴 | `−pos * 0.005` | 0.005 | ✅ | ✅ | ❌ 无 | ✅ 无（对称） |
| coupling | 三轴 | `C_cross × velocity` | 0.03 | ✅ | ✅ | ✅ openness | ✅ 无 |
| noise | 三轴 | `uniform(−0.004, +0.004)` | 0.004 | ✅ | ✅ | ❌ 无 | ✅ 无（对称） |

## 2. 三个核心缺陷的代码路径

### 2.1 X 轴二值分叉（§0, §4）

**位置**：`forces.py::economic_force_x` 与 `forces.py::interpret_event`

```python
# economic_force_x
gov = (trust + authority_preference) / 2.0          # 连续变量 ∈ [0,1]
econ_dir = -1.0 if gov >= 0.5 else 1.0              # ← 二值分类器！
return pressure * 0.4 * econ_dir * wx

# interpret_event
x_dir = -1.0 if gov >= 0.5 else 1.0                 # ← 同一二值分类器
dx = sx * x_dir * conviction
```

`gov` 是连续人格变量，但被压缩成 `{+1, −1}` 两个方向。`gov=0.49` 与 `gov=0.51`
产生 **完全相反且量级相同** 的力，把中间人格强制推向左右两极，天然制造 X 双峰。

### 2.2 Z 轴永久 Z+ 漂移（§0, §8）

**位置**：`forces.py::community_force_z`

```python
isolation = 1.0 - min(1.0, n_friends / avg_degree)   # ∈ [0,1]
return ((1.0 - isolation) * 0.5 - isolation * empathy) * strength * wz
```

分解：`(1.0 - isolation) * 0.5` **恒 ≥ 0**（联结良好 → +0.5），`- isolation * empathy`
仅在孤立时为负。默认社会网络下多数 Agent 联结良好（isolation≈0），于是力 ≈ **+0.5**，
无论人格、事件、资源如何，都持续向 Z+（个人主义）漂移。

### 2.3 Y 轴弱动力（§0, §13）

**位置**：`forces.py::authority_force_y`

```python
legitimacy_stress = 0.5 - trust_gov
return legitimacy_stress * (authority - 0.5) * 2.0 * 0.03 * wy
```

Y 轴**唯一**驱动源是 `trust_in_government`（合法性压力），强度仅 0.03，且被
anchor(0.02) + center(0.005) + trust 惯性平滑同时压制。无冲突、无安全、无制度
绩效等独立信号，长期趋于静默。

## 3. 其他观测

- `interpret_event` 的 Z 方向是 `-(empathy − 0.5) * 2`，属于 §9 禁止的
  「empathy → 永远 Z-」硬映射。
- `detect_axis_dominance`（observability.py）只依据**坐标方差**判断主导轴，无法
  区分「整体平移」与「真正极化」（§19），需要用**力/速度**辅助判断。
- `boundary_concentration` 只统计「靠近任意边界」，不区分具体哪个边界在积累人口
  （§30：需要 X−/X+/Y−/Y+/Z−/Z+ 六方向）。
- noise 默认 0.004 偏大，§24 要求降到 0.001 且证明「noise=0 仍不塌缩」。

## 4. 修复映射

| 缺陷 | 修复 | 对应 § |
|---|---|---|
| X 二值 | 连续 `econ_bias`（tanh/线性）+ deadzone + saturation | §4–§7 |
| Z 单向 | `autonomy_preference` vs `belonging_need` 双向偏好 + group_pressure | §8–§12 |
| Y 弱 | 多驱动：legitimacy + security + repression + institutional | §13–§15 |
| 事件 Z 硬映射 | 事件 Z 方向改用双向偏好，不再 `empathy → Z-` | §9 |
| 方差主导误判 | force/velocity 驱动的 `AxisDominanceDetector` | §17 |
| 边界不分向 | 六方向边界统计 | §30 |
| noise 偏大 | 降到 0.001 + OFF/ON 测试 | §24 |
