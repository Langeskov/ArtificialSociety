# Artificial Society v0.4.5
## Event Ecology & Causal Dynamics

## 0. 版本定位

基于当前 `ArtificialSociety v0.4.4` 继续开发。

当前系统已经具备：

```text
Agent
→ Relationship
→ Group
→ Identity
→ Information
→ Behavior
→ Resource
→ Economy
→ Production Structure
→ Crisis Manager
→ Political Dynamics
```

但是长时间运行仍然会出现明显的：

```text
丑闻
→ 政治运动
→ 自然灾害
→ 资源繁荣
→ 丑闻
→ ...
```

或者：

```text
经济危机
→ 恢复
→ 粮食稳定
→ 再次经济危机
```

这不是简单的“事件概率过高”。

当前 Event Engine 仍然存在一个结构性问题：

> **部分事件是由随机数直接生成，而不是由社会状态和因果条件产生。**

例如当前外生事件仍类似：

```python
rng.choice([
    "natural_disaster",
    "technology_breakthrough",
    "resource_boom",
    "scandal"
])
```

这会让人工社会变成：

```text
社会状态
+
随机事件轮盘
```

而不是：

```text
社会状态
→ 因果压力
→ 事件
→ 社会响应
```

因此 v0.4.5 不以增加更多事件类型为目标。

本版本的核心目标是：

> **将 Event Engine 从“随机事件生成器”升级为“社会状态驱动的事件生态系统”。**

---

# 1. v0.4.5 核心目标

必须完成：

```text
[1] Endogenous / Exogenous / Recovery 三类事件分离
[2] 所有内生事件拥有明确 Trigger Condition
[3] 事件不能仅由 Social Temperature 随机触发
[4] 外生事件按 simulated day 低频触发
[5] 事件拥有 causal score
[6] 事件拥有 source / mechanism / evidence
[7] 事件之间通过因果链连接
[8] 事件触发具有 persistence / threshold / cooldown
[9] 事件不能因为自身产生的恢复事件再次触发自己
[10] 同类事件不能在短时间内重复
[11] 不同事件不能无依据地互相串联
[12] Recovery 从 Event 降级为 Crisis State Transition
[13] Event Timeline 能区分 cause / effect / recovery / exogenous
[14] 增加事件生态诊断
[15] 增加 event-ablation / causal testing
```

---

# 2. Event 的三种来源

所有 Event 必须具有：

```text
source_type
```

只能为：

```text
ENDOGENOUS
EXOGENOUS
RECOVERY
```

### ENDOGENOUS

来自社会内部状态：

```text
economic_crisis
food_shortage
protest
political_movement
unemployment
conflict
market_panic
scandal
group_split
migration_wave
```

### EXOGENOUS

来自系统之外：

```text
natural_disaster
pandemic
external_shock
rare_technology_shock
```

### RECOVERY

只是状态变化记录：

```text
economic_recovery
food_stabilization
protest_recovery
resource_stabilization
```

---

# 3. Event 不再等于 Crisis

必须彻底分离：

```text
Crisis State
≠
Event
```

例如：

```text
Economic Crisis
state = ACTIVE
```

可以产生：

```text
Event:
economic_crisis_started
```

之后：

```text
ACTIVE
→ RECOVERING
→ COOLDOWN
```

不需要每个状态变化都创建 Event。

---

# 4. Event 结构升级

Event 至少增加：

```python
Event:
    event_id
    type
    source_type
    tick
    region
    affected_agents
    affected_groups

    severity
    intensity
    duration

    trigger_score
    causal_confidence

    cause_event_id
    cause_mechanism

    evidence
    effects
```

---

# 5. Trigger / Cause / Effect 分离

一个 Event 必须拥有：

```text
Trigger
```

表示：

> 为什么它现在有可能发生。

以及：

```text
Cause
```

表示：

> 哪些社会机制推动它发生。

以及：

```text
Effect
```

表示：

> 它实际改变了什么。

例如：

```text
Economic Crisis

Trigger:
unemployment > 18%

Cause:
production_gap
+
price_pressure
+
liquidity_stress

Effect:
employment ↓
income ↓
production_disruption ↑
trust ↓
```

---

# 6. Event Trigger Registry

新增：

```text
engine/event/triggers.py
```

定义：

```text
EventTrigger
```

接口：

```python
score(society, context) -> float
```

以及：

```python
should_trigger(score, state, history) -> bool
```

每种内生 Event 注册自己的 Trigger。

---

# 7. Economic Crisis Trigger

禁止继续：

```text
economic_crisis
=
0.45*broke
+
0.25*hungry
+
0.30*inequality
```

单独触发。

应该改成：

```text
economic_pressure =
production_gap
+
unemployment
+
price_pressure
+
liquidity_stress
+
resource_shortage
```

其中：

```text
inequality
```

只是：

```text
social_stress
```

而不是直接：

```text
economic_crisis
```

---

# 8. Food Crisis Trigger

Food Crisis 应使用：

```text
food_stock
daily_consumption
days_of_supply
regional_hunger
production_gap
trade_gap
```

而不是仅：

```text
hungry_ratio
```

例如：

```text
food_crisis_score =
shortage_duration
+
low_stock_buffer
+
regional_hunger
+
production_gap
```

---

# 9. Protest Trigger

抗议必须来自：

```text
grievance
+
mobilization
+
information
+
group
```

例如：

```text
protest_score =
grievance
×
mobilization
×
information_reach
×
group_support
```

不能再：

```text
social_temperature > 0.4
→ random()
```

---

# 10. Political Movement Trigger

政治运动必须比 Protest 更严格。

例如：

```text
movement_score =
persistent_grievance
×
group_cohesion
×
information_cascade
×
political_opportunity
```

必须：

```text
duration > threshold
```

并且：

```text
至少一个 Group
```

参与。

不能由 Society Temperature 单独触发。

---

# 11. Scandal Trigger

Scandal 不允许随机产生。

必须来自：

```text
agent behavior
group behavior
information
```

例如：

```text
Agent / Group
↓
违规行为
↓
Information detected
↓
information spread
↓
trust collapse
↓
Scandal
```

如果没有：

```text
violation
+
information exposure
```

不能产生：

```text
scandal
```

---

# 12. Resource Boom Trigger

Resource Boom 不再随机。

只能来自：

```text
production increase
technology breakthrough
resource discovery
successful trade expansion
```

例如：

```text
new production unit
+
production capacity ↑
```

触发：

```text
RESOURCE_BOOM
```

或者：

```text
technology_breakthrough
→ production capacity ↑
→ resource boom
```

---

# 13. Natural Disaster

Natural Disaster 是真正的：

```text
EXOGENOUS
```

可以随机。

但：

```text
random event
```

必须使用：

```text
daily probability
```

不能：

```text
per tick probability
```

否则：

```text
ticks_per_day
```

改变时事件频率也会改变。

---

# 14. 外生事件概率

配置：

```yaml
events:
  exogenous:
    enabled: true

    natural_disaster:
      daily_probability: 0.001

    pandemic:
      daily_probability: 0.0001

    external_shock:
      daily_probability: 0.0005
```

具体默认参数以实际 calibration 为准。

---

# 15. Exogenous Event Spatial Scope

Natural Disaster 等外生事件必须具有：

```text
region
```

例如：

```text
Region B
↓
Natural Disaster
```

默认只影响：

```text
Region B
```

通过：

```text
trade
migration
information
```

逐渐传播。

不能：

```text
natural_disaster
→ whole society instant effect
```

---

# 16. Event Trigger Persistence

所有内生 Event 必须：

```text
score > trigger_threshold
```

持续：

```text
N ticks
```

才触发。

例如：

```yaml
events:
  triggers:
    protest:
      threshold: 0.60
      persistence_hours: 12
```

这样：

```text
短暂 anger ↑
```

不会直接形成：

```text
nationwide protest
```

---

# 17. Hysteresis

所有 Crisis / Event Trigger 必须有：

```text
trigger_threshold
resolve_threshold
```

例如：

```text
trigger = 0.70
resolve = 0.40
```

避免：

```text
0.69
0.70
0.69
0.70
```

不断启动/结束。

---

# 18. Cooldown

事件结束后：

```text
cooldown
```

期间不允许同类型事件重新产生。

但：

> Cooldown 不应该改变真实社会状态。

它只控制：

```text
duplicate event emission
```

---

# 19. Event Budget

每个模拟日计算：

```text
candidate_events
```

然后根据：

```text
causal_score
severity
urgency
spatial_scope
```

排序。

支持：

```yaml
events:
  daily_major_event_budget: 2
```

默认一个 Society 每日最多生成少量 Major Events。

不是：

```text
每个事件都独立 random()
```

---

# 20. Event Candidate Pipeline

新的 Event Engine：

```text
Society State
↓
Generate Candidate Triggers
↓
Calculate Trigger Score
↓
Check Persistence
↓
Check Cooldown
↓
Check Causal Evidence
↓
Rank
↓
Apply Event Budget
↓
Create Events
↓
Apply Effects
```

不要在业务代码中随处：

```python
if random.random() < ...
```

生成事件。

---

# 21. Event Causal Evidence

每个候选事件必须记录：

```text
evidence = {
    "production_gap": 0.72,
    "unemployment": 0.61,
    "price_pressure": 0.44
}
```

最终：

```text
causal_confidence
```

由证据计算。

---

# 22. Event Source Trace

每一个 Event 必须能够追溯：

```text
Event
↓
Trigger
↓
Evidence
↓
Cause
↓
Mechanism
```

UI 点击 Event 时显示：

```text
WHY DID THIS HAPPEN?

Production gap       0.72
Unemployment         0.61
Liquidity stress     0.44

Trigger Score        0.71
Confidence            0.83
```

---

# 23. Causal Chain

Event Chain 扩展为：

```text
STATE
 ↓
TRIGGER
 ↓
EVENT
 ↓
MECHANISM
 ↓
EFFECT
 ↓
STATE CHANGE
```

例如：

```text
Unemployment ↑
 ↓
Economic Crisis Trigger
 ↓
Economic Crisis
 ↓
Income ↓
 ↓
Resource Pressure ↑
 ↓
Protest Trigger
 ↓
Protest
 ↓
Production disruption
```

---

# 24. Prevent Immediate Recursive Trigger

一个事件产生的效果：

```text
Event A
→ Effect B
```

不能在同一个 tick 立即触发：

```text
B
→ Event A
```

或：

```text
A
→ B
→ A
```

必须：

```text
minimum causal delay
```

至少：

```yaml
events:
  causal_delay:
    min_ticks: 5
```

---

# 25. Causal Cooldown

如果：

```text
Economic Crisis
→ Protest
```

则：

```text
Economic Crisis
```

不能在：

```text
few ticks
```

内再次由：

```text
Protest
```

触发。

需要：

```text
causal_memory
```

记录：

```text
source
target
timestamp
```

---

# 26. Recovery 不重新触发危机

明确保证：

```text
Recovery Event
```

不能参与：

```text
political_force
economic_pressure
social_temperature
```

也不能：

```text
Recovery
→ new crisis
```

Recovery 只是：

```text
state transition notification
```

---

# 27. Recovery UI

Event Timeline 不再把：

```text
protest
→ recovery
```

显示成两个平等事件。

建议显示：

```text
PROTEST
ACTIVE
███████████░░

↓ recovery

PROTEST
RECOVERING
█████░░░░░░░

↓ resolved
```

恢复事件只能作为：

```text
secondary notification
```

---

# 28. Event Classification

UI 中每个 Event 显示：

```text
[ENDOGENOUS]
[EXOGENOUS]
[RECOVERY]
```

例如：

```text
[NATURAL DISASTER] EXOGENOUS

[ECONOMIC CRISIS] ENDOGENOUS

[ECONOMIC RECOVERY] RECOVERY
```

---

# 29. Event Frequency Dashboard

增加：

```text
EVENT ECOLOGY

Endogenous:
  12

Exogenous:
   1

Recovery:
   8

Uncaused:
   0
```

尤其增加：

```text
events_without_causal_evidence
```

目标：

```text
= 0
```

除了：

```text
EXOGENOUS
```

事件。

---

# 30. Event Entropy

统计：

```text
event_distribution
```

例如：

```text
Economic Crisis  32%
Protest           28%
Conflict          18%
Scandal            5%
Natural Disaster   1%
```

如果：

```text
某两个事件
```

长期占据：

```text
> 80%
```

显示：

```text
EVENT DOMINANCE
```

这用于检测事件循环。

---

# 31. Event Loop Detector

新增：

```text
engine/event/loops.py
```

检测：

```text
A → B → A
A → B → C → A
```

输出：

```text
LOOP DETECTED

Food Crisis
 ↓
Protest
 ↓
Production Loss
 ↓
Food Crisis

Period: 6.2 days
Strength: 0.63
```

---

# 32. Loop Strength

定义：

```text
loop_strength =
product(edge_strength)
```

如果：

```text
loop_strength < 0.2
```

视为弱反馈。

如果：

```text
loop_strength > 0.8
```

显示：

```text
STRONG SELF-REINFORCING LOOP
```

---

# 33. Event Periodicity

记录同类事件之间：

```text
delta_t
```

如果：

```text
mean(delta_t)
std(delta_t)
```

高度稳定：

```text
periodic_event = true
```

例如：

```text
Economic Crisis
Day 12
Day 18
Day 24
Day 30
```

这是明显系统性振荡。

---

# 34. Event Oscillation Report

增加：

```text
docs/event_ecology_v0.4.5_report.md
```

至少报告：

```text
Event count
Endogenous count
Exogenous count
Recovery count

Uncaused count
Loop count
Loop strength

Recurring events
Mean period
Period variance

Largest causal chain
Largest feedback loop
```

---

# 35. Event Ablation

增加实验：

```text
no_exogenous_events
no_protest
no_economic_crisis
no_scandal
no_political_movement
no_recovery_notifications
```

比较：

```text
event count
resource stability
political polarization
group fragmentation
social temperature
```

---

# 36. 重要：Event-less Baseline

必须运行：

```text
all_exogenous_events = OFF
```

然后：

```text
1000 Agents
100 simulated days
5 seeds
```

观察：

```text
社会是否自己产生事件？
```

如果：

```text
YES
```

那么这些事件才真正值得研究。

如果：

```text
NO
```

则说明：

> 当前社会没有足够的内生动力。

这个结果同样有价值。

---

# 37. Exogenous-only Baseline

反向运行：

```text
ENDOGENOUS EVENTS OFF
EXOGENOUS ON
```

观察：

```text
事件是否只是外部冲击驱动？
```

---

# 38. Event Causality Scorecard

实验结束后生成：

```text
Event Causality

Economic Crisis:
  endogenous: 94%
  exogenous: 0%
  unclear: 6%

Protest:
  endogenous: 100%

Scandal:
  endogenous: 78%
  exogenous: 0%
  unclear: 22%
```

目标不是让数字全部 100%。

目标是：

> **开发者能够知道社会为什么产生这个事件。**

---

# 39. 事件与政治动力学

继续保持：

```text
Event
↓
Political Interpreter
↓
Political Force
↓
X/Y/Z
```

禁止：

```text
Event type
→ fixed X/Y/Z delta
```

例如：

```text
scandal
```

不应直接：

```text
Y -= 0.05
```

而应该：

```text
scandal
→ trust / belief
→ Agent interpretation
→ Y response
```

---

# 40. 事件与资源动力学

同样：

```text
Economic Crisis
```

必须作用于：

```text
production
income
employment
prices
```

再通过资源系统影响 Agent。

禁止：

```text
economic_crisis
→ food -= 20
```

直接凭空改变资源。

---

# 41. 自然灾害

自然灾害是例外：

```text
EXOGENOUS
```

可以直接造成：

```text
resource loss
production loss
regional disruption
```

但必须：

```text
region-local
```

并且：

```text
severity
```

决定影响。

---

# 42. Resource Boom

Resource Boom 必须从经济状态产生。

允许：

```text
production_capacity ↑
technology_breakthrough
trade_discovery
resource_discovery
```

形成：

```text
resource_boom
```

而不是：

```text
random.choice("resource_boom")
```

---

# 43. Technology Breakthrough

同理：

```text
R&D activity
+
quaternary sector
+
investment
```

达到：

```text
innovation_score
```

后：

```text
technology_breakthrough
```

可以产生：

```text
production_efficiency ↑
```

但必须有：

```text
causal evidence
```

---

# 44. Scandal

Scandal 必须成为第一个完整的：

```text
Behavior
→ Information
→ Belief
→ Event
```

测试案例。

例如：

```text
Agent / Group behavior
↓
suspicious action
↓
information detected
↓
rumor
↓
belief spread
↓
public trust loss
↓
scandal event
```

---

# 45. Event Severity

Severity 不应该完全随机：

```python
severity = rng.random()
```

改成：

```text
severity =
base
× trigger_strength
× exposure
× propagation
```

允许少量随机扰动：

```text
± small_noise
```

这样同一个机制下：

```text
事件有大小差异
```

但不是：

```text
完全随机大小
```

---

# 46. Event Scope

继续使用：

```text
INDIVIDUAL
GROUP
REGIONAL
SOCIETY
```

Event 默认尽可能小范围开始。

只有：

```text
propagation
```

才升级。

例如：

```text
Group conflict
↓
regional conflict
↓
society-wide conflict
```

而不是直接：

```text
GROUP conflict
→ entire society
```

---

# 47. Event Propagation

事件传播必须经过：

```text
information
trade
migration
group relations
```

不能：

```text
event
→ all agents
```

立即同步。

---

# 48. Event Saturation

社会对同一种事件存在：

```text
adaptation
```

例如：

```text
第一次 crisis
→ impact = 1.0

第二次类似 crisis
→ impact = 0.8

第三次
→ impact = 0.65
```

但不要直接硬编码次数。

使用：

```text
event_memory
institutional_adaptation
```

形成。

---

# 49. Event Learning

如果 Society 经历过：

```text
food shortage
```

以后：

```text
storage
trade
sharing
```

应该提高。

这是社会学习。

目标：

```text
第一次危机
→ 剧烈

后来同类危机
→ 更容易吸收
```

除非：

```text
shock
```

超过社会适应能力。

---

# 50. 新事件生成顺序

Simulation Tick 中：

```text
1. Update resources
2. Update production / economy
3. Complete behaviors
4. Update information
5. Update group / identity
6. Calculate social state
7. Calculate event triggers
8. Rank candidate events
9. Apply event budget
10. Create endogenous events
11. Rare exogenous events
12. Apply effects
13. Political dynamics
14. Crisis state transitions
15. Metrics
```

不能：

```text
random events
→ immediate political response
→ same tick another event
```

无限递归。

---

# 51. Same-Tick Recursion Guard

同一个 tick：

```text
Event A
→ Event B
→ Event C
```

最多允许：

```yaml
events:
  max_causal_depth_per_tick: 2
```

超出：

```text
defer to next tick
```

避免事件爆炸。

---

# 52. Event Queue

建议新增：

```text
engine/event/queue.py
```

而不是：

```text
new_events.append(...)
```

然后立即继续处理。

Event Queue 支持：

```text
tick
priority
causal_depth
source
```

这样：

```text
Event A
```

产生：

```text
Event B
```

B 可以排到：

```text
tick + delay
```

而不是立刻执行。

---

# 53. Event Priority

优先级：

```text
EXOGENOUS
CRITICAL ENDOGENOUS
ENDOGENOUS
RECOVERY
```

恢复事件最低。

避免：

```text
recovery
```

干扰真正的社会因果。

---

# 54. Event System Performance

禁止：

```text
每 tick
每个 Event
扫描全部历史
```

使用：

```text
rolling history
indexes
active event registry
recent causal edges
```

保持 1000 Agent 模拟性能。

---

# 55. Dashboard

新增：

```text
EVENT ECOLOGY
```

显示：

```text
Endogenous      8
Exogenous       1
Recovery        5

Causal Events   8
Uncaused        0

Active Loops    1
Strong Loops    0

Event Diversity 0.72
```

---

# 56. Event Timeline

每条事件：

```text
[ENDOGENOUS]
Economic Crisis
tick 3070

Trigger:
unemployment 18%
production gap 23%

Cause:
production decline

Effect:
income ↓
```

而不是只有：

```text
经济危机
高不平等与经济压力引发
```

---

# 57. Event Causal Graph

显示：

```text
Production Gap
      ↓
Unemployment
      ↓
Economic Crisis
      ↓
Income Loss
      ↓
Resource Pressure
      ↓
Protest
```

支持点击每一节点查看：

```text
evidence
score
source
effect
```

---

# 58. Testing

新增：

```text
tests/test_event_ecology.py
tests/test_event_triggers.py
tests/test_event_loops.py
```

至少：

```text
test_endogenous_event_requires_evidence
test_exogenous_event_is_daily_rate
test_event_persistence
test_event_hysteresis
test_event_cooldown
test_event_budget
test_causal_delay
test_causal_depth_limit
test_recovery_not_trigger
test_event_source_type
test_event_severity_is_causal
test_event_scope
test_event_loop_detection
test_event_periodicity
test_scandal_requires_information
test_resource_boom_requires_production_change
```

---

# 59. 核心 Regression Test

必须运行：

```text
1000 Agents
100 simulated days
5 seeds
```

默认：

```text
Exogenous events ON
```

然后统计：

```text
total_events
unique_event_types
endogenous_ratio
exogenous_ratio
recovery_ratio
loop_count
periodic_loop_count
```

---

# 60. “事件轮盘”回归测试

特别测试：

```text
random external shock generator
```

在默认设置下：

```text
natural_disaster
technology_breakthrough
resource_boom
scandal
```

不能以：

```text
approximately equal frequency
```

随机出现。

如果系统运行 100 天：

```text
scandal = 12
natural_disaster = 8
resource_boom = 11
technology = 9
```

说明仍然存在事件轮盘。

默认测试应要求：

> 大多数事件必须来自 Endogenous Trigger。

---

# 61. Endogenous Event Ratio

建议默认长跑：

```text
ENDOGENOUS >= 70%
EXOGENOUS <= 10%
RECOVERY <= 30%
```

这些不是物理真理，只作为 diagnostics baseline。

实际比例需要记录，不要强制达到特定数字。

---

# 62. No-event Baseline

执行：

```text
exogenous OFF
```

目标：

```text
社会仍然能够产生一些内生事件
```

例如：

```text
economic crisis
unemployment
group conflict
protest
scandal
```

如果完全没有事件：

> 说明社会本身还没有足够的内生动力。

不要通过重新加入随机事件掩盖。

---

# 63. All-events-off Baseline

执行：

```text
ENDOGENOUS OFF
EXOGENOUS OFF
```

这时：

```text
Society
```

仍应该可以：

```text
生产
交易
就业
迁移
形成 Group
传播 Information
发生政治变化
```

用于确认：

> 事件不是整个社会模拟的发动机。

---

# 64. Event Impact Experiment

对每一种 Event：

```text
one event injected manually
```

观察：

```text
100 ticks
```

记录：

```text
resource effect
behavior effect
group effect
identity effect
political effect
recovery time
```

这样可以建立：

```text
Event Response Matrix
```

---

# 65. Event Response Matrix

例如：

```text
                     Resource   Group   Identity   Politics
Food Crisis             High      Med      Med        Med
Economic Crisis         High      Med      Med        High
Scandal                 Low       High     High       High
Natural Disaster        High      Med      Low        Low
Technology Breakthrough Med       Low      Low        Med
```

实际数值由实验生成。

不要人工填写。

---

# 66. 版本边界

v0.4.5 不新增：

```text
企业
复杂劳动力市场
工资体系
培训
GPU
多线程
完整政府
选举
LLM
```

这些机制以后继续加入。

本版本唯一目标：

> **先让“事件”本身成为可信的社会因果结果。**

---

# 67. Hermes-Agent 执行顺序

严格：

```text
P0
Event Source Separation
        ↓
P0
Event Trigger Registry
        ↓
P0
Remove Random Endogenous Events
        ↓
P0
Event Queue / Causal Delay
        ↓
P0
Trigger Persistence / Hysteresis / Cooldown
        ↓
P1
Causal Evidence
        ↓
P1
Endogenous Scandal
        ↓
P1
Causal Resource Boom
        ↓
P1
Event Scope / Propagation
        ↓
P1
Loop Detector
        ↓
P2
Event Ecology Dashboard
        ↓
P2
Ablation / Event Injection Experiments
```

---

# 68. 最终验收

必须达到：

```text
[✓] 默认运行不再随机轮换“丑闻/灾害/繁荣/技术突破”
[✓] Endogenous Event 有明确原因
[✓] Scandal 有行为/信息来源
[✓] Protest 有 grievance + mobilization
[✓] Economic Crisis 有真正经济证据
[✓] Food Crisis 有资源证据
[✓] Resource Boom 有生产/技术/贸易来源
[✓] Natural Disaster 是真正的 Exogenous Event
[✓] Recovery 不再作为正常事件参与因果反馈
[✓] 同一事件不会在短时间内重复
[✓] Event 有因果延迟
[✓] Event 有空间范围
[✓] Event 有 causal confidence
[✓] 可以检测 A→B→A 循环
[✓] 可以检测周期性事件
[✓] 可以关闭所有外生事件运行社会
[✓] 可以关闭所有事件运行社会
[✓] v0.4.4 劳动力/生产/结构测试全部通过
```

---

# 69. 最终成功定义

完成 v0.4.5 后，事件系统应该从：

```text
Random Event Generator
```

变成：

```text
                        Society State
                              ↓
                     Potential Pressures
                              ↓
                       Event Triggers
                              ↓
                     Evidence / Cause
                              ↓
                        Event Queue
                              ↓
                           Event
                              ↓
                 ┌────────────┴────────────┐
                 ↓                         ↓
              Effects                  Information
                 ↓                         ↓
             New State                  Beliefs
                 ↓                         ↓
                 └────────────┬────────────┘
                              ↓
                       Social Response
                              ↓
                       Political Change
                              ↓
                        New Society State
                              ↺
```

最终真正想看到的应该是：

```text
资源短缺
→ 生产下降
→ 价格上涨
→ 失业增加
→ 经济危机

而不是：

经济危机
→ 随机灾害
→ 随机资源繁荣
→ 随机丑闻
```

以及：

```text
真实社会压力
→ 一次抗议
→ 部分恢复
→ 行为适应
→ 新平衡
```

而不是：

```text
抗议
→ recovery
→ 抗议
→ recovery
→ 抗议
```

因此，这一版不是在追求“事件更少”，而是在追求：

> **事件必须有来处，有机制，有证据，有延迟，有后果，并且能够被反事实实验验证。**

只有做到这一点，后续的就业、企业、工资、培训、迁移和产业结构变化才真正有意义。