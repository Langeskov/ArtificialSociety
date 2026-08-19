# Temporal Model v0.4.2

## 时间单位定义

| 概念 | 值 | 说明 |
|---|---|---|
| 1 tick | 1/100 天 = 0.01 天 = 14.4 分钟 | 最小模拟时间步 |
| 1 day | 100 ticks | 一个模拟日 |
| 1 month | 30 days = 3000 ticks | 一个模拟月 |
| 1 year | 12 months = 36000 ticks | 一个模拟年 |

## Clock 属性 (engine/simulation/clock.py)

| 属性 | 类型 | 说明 |
|---|---|---|
| `tick` | int | 当前 tick 数 |
| `ticks_per_day` | int | 每天 tick 数（默认 100） |
| `simulated_days` | float | 连续模拟天数 (tick / ticks_per_day) |
| `dt_days` | float | 每 tick 的时间增量 (1 / ticks_per_day) |
| `simulated_hours` | float | 连续模拟小时数 |
| `hour_of_day` | int | 当前模拟小时 (0-23) |
| `day` | int | 月内天数 (1-30) |
| `month` | int | 年内月份 (1-12) |
| `year` | int | 年份 |

## 资源流频率 (v0.4.2 §5-6)

所有资源率统一为 **per-day**，引擎按 `dt_days` 换算：

```
per_tick = per_day × dt_days
per_day = per_tick × ticks_per_day
```

| 系统 | 频率 | 说明 |
|---|---|---|
| 基础代谢消费 | 每 tick | food_consumption_per_agent × dt_days |
| 税收 | 每天 (collect_tax) | money × tax_rate |
| 行为系统 | 每 tick | 12 种行为评估 |
| 政治更新 | 每 tick | 力计算 + 位置更新 |
| 群体生命周期 | 每 tick | 合并/分裂/解散 |
| 信息传播 | 每 tick | 沿网络传播 |
| 事件衰减 | 每 tick | duration 递减 |
| 指标计算 | 每 step (N ticks) | 宏观指标 |

## Crisis State Machine (v0.4.2 §29)

```
NORMAL → WARNING → ACTIVE → SEVERE → RECOVERING → COOLDOWN → NORMAL
```

| 状态 | 条件 | 说明 |
|---|---|---|
| NORMAL | metric < trigger_threshold | 正常状态 |
| WARNING | metric > trigger_threshold, 持续 < persistence_ticks | 预警 |
| ACTIVE | metric > trigger_threshold, 持续 >= persistence_ticks | 危机激活 |
| SEVERE | metric > trigger_threshold × 1.5 | 严重危机 |
| RECOVERING | metric < resolve_threshold | 恢复中 |
| COOLDOWN | 危机解决后 N 天 | 冷却期，不重新触发 |

### Hysteresis (§14)

触发阈值 > 解决阈值，防止在阈值附近反复开关：
- food_crisis: trigger=0.25, resolve=0.12
- protest: trigger=0.15, resolve=0.08

### Persistence (§15)

条件必须持续 N ticks 才触发：
- food_crisis: 50 ticks (≈12 小时)
- protest: 30 ticks (≈7 小时)

### Cooldown (§16)

解决后 N 天内不重新触发：
- food_crisis: 2 天
- protest: 2 天

## Production Multiplier Dynamics (§19)

v0.4.2 关键变更：临时干扰 vs 永久 ratchet

```
production_multiplier: 基础乘数，向 1.0 阻尼恢复
production_disruption: 临时干扰，自动衰减 (decay=0.92/tick)
effective_pm = max(0.3, multiplier - disruption)
```

事件影响的是 disruption（临时），不是 multiplier（永久）：
- 抗议: disruption += 0.08
- 自然灾害: disruption += 0.2 × severity
- 经济危机: disruption += 0.15 × severity
- 战争: disruption += 0.25 × severity

## 配置结构

```yaml
economy:
  daily:
    food_consumption_per_agent: 5.0   # per day
    energy_consumption_per_agent: 3.0 # per day
  recovery:
    damping: 0.85
    max_rate_per_day: 0.15
    disruption_decay: 0.92

events:
  crisis:
    food:
      trigger_threshold: 0.25
      resolve_threshold: 0.12
      trigger_persistence_ticks: 50
      cooldown_days: 2
    protest:
      trigger_threshold: 0.15
      resolve_threshold: 0.08
      trigger_persistence_ticks: 30
      cooldown_days: 2
```
