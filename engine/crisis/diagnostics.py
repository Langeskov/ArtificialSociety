"""Feedback Loop Diagnostics & Oscillation Detector (v0.4.2 §30–§34).

检测社会系统中的正/负反馈环和周期性振荡：
  - 正反馈环：food shortage → anger → protest → production loss → food shortage
  - 负反馈环：food shortage → trade → food import → recovery
  - 振荡检测：food、temperature、protest、production_multiplier 的周期性模式

使用滚动窗口和增量指标，避免每 tick O(T) 扫描。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


@dataclass
class OscillationDetector:
    """检测指标的周期性振荡（§31）。

    使用简单的峰值检测：在滚动窗口中寻找局部极值，
    如果连续发现 >= min_cycles 个周期，报告振荡。
    """
    window_size: int = 500  # 滚动窗口大小（ticks）
    min_cycles: int = 3     # 最少周期数才报告
    _values: deque = field(default_factory=lambda: deque(maxlen=1000))
    _tick_count: int = 0

    def __post_init__(self):
        self._values = deque(maxlen=self.window_size)

    def update(self, value: float) -> None:
        self._values.append(value)
        self._tick_count += 1

    def detect(self) -> dict:
        """检测振荡，返回 {detected, period_ticks, amplitude}。"""
        if len(self._values) < self.window_size // 2:
            return {"detected": False, "period_ticks": 0, "amplitude": 0.0}

        vals = list(self._values)
        n = len(vals)
        mean = sum(vals) / n
        if mean < 1e-6:
            return {"detected": False, "period_ticks": 0, "amplitude": 0.0}

        # 简单峰值检测：找局部极大值（比左右各1个点高即可）
        peaks = []
        for i in range(1, n - 1):
            if vals[i] > vals[i-1] and vals[i] > vals[i+1]:
                peaks.append(i)

        if len(peaks) < self.min_cycles:
            return {"detected": False, "period_ticks": 0, "amplitude": 0.0}

        # 计算平均周期
        periods = [peaks[i+1] - peaks[i] for i in range(len(peaks) - 1)]
        if not periods:
            return {"detected": False, "period_ticks": 0, "amplitude": 0.0}
        avg_period = sum(periods) / len(periods)

        # 计算振幅（峰值均值 vs 谷值均值）
        peak_mean = sum(vals[p] for p in peaks) / len(peaks)
        # 找谷值
        troughs = []
        for i in range(1, n - 1):
            if vals[i] < vals[i-1] and vals[i] < vals[i+1]:
                troughs.append(i)
        trough_mean = sum(vals[t] for t in troughs) / max(len(troughs), 1) if troughs else mean
        amplitude = (peak_mean - trough_mean) / max(mean, 1e-6)

        return {
            "detected": len(peaks) >= self.min_cycles,
            "period_ticks": round(avg_period, 1),
            "amplitude": round(amplitude, 4),
            "cycles_found": len(peaks),
        }


@dataclass
class FeedbackDiagnostics:
    """反馈环诊断（§33-§34）。

    通过相关性检测正/负反馈环的强度。
    """
    window_size: int = 200
    _food_history: deque = field(default_factory=lambda: deque(maxlen=200))
    _anger_history: deque = field(default_factory=lambda: deque(maxlen=200))
    _protest_history: deque = field(default_factory=lambda: deque(maxlen=200))
    _production_history: deque = field(default_factory=lambda: deque(maxlen=200))

    def update(self, food_avg: float, anger_avg: float,
               protest_count: int, production_pm: float) -> None:
        self._food_history.append(food_avg)
        self._anger_history.append(anger_avg)
        self._protest_history.append(float(protest_count))
        self._production_history.append(production_pm)

    def analyze(self) -> dict:
        """分析反馈环强度。"""
        if len(self._food_history) < 50:
            return {"positive_feedback": 0.0, "negative_feedback": 0.0,
                    "feedback_ratio": 0.0, "dominant": "unknown"}

        foods = list(self._food_history)
        angers = list(self._anger_history)
        protests = list(self._protest_history)
        prods = list(self._production_history)
        n = len(foods)

        # 正反馈：food↓ → anger↑ → protest↑ → production↓ → food↓
        # 检测：food 与 production 的正相关（同向变化）
        pos = _correlation(foods, prods)

        # 负反馈：food↓ → trade↑ → recovery → food↑
        # 检测：food 自相关（滞后恢复）
        neg = _autocorrelation(foods, lag=max(10, n // 4))

        ratio = abs(pos) / max(abs(neg), 0.01) if neg != 0 else float('inf')

        if ratio > 1.5:
            dominant = "UNSTABLE_POSITIVE"
        elif ratio > 0.8:
            dominant = "OSCILLATION_RISK"
        else:
            dominant = "STABLE_NEGATIVE"

        return {
            "positive_feedback": round(pos, 4),
            "negative_feedback": round(neg, 4),
            "feedback_ratio": round(ratio, 4),
            "dominant": dominant,
        }


def _correlation(xs: list, ys: list) -> float:
    """Pearson 相关系数。"""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs[:n]) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys[:n]) / n)
    if sx < 1e-10 or sy < 1e-10:
        return 0.0
    return cov / (sx * sy)


def _autocorrelation(xs: list, lag: int = 10) -> float:
    """自相关系数（lag 步）。"""
    n = len(xs)
    if n < lag + 3:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n
    if var < 1e-10:
        return 0.0
    cov = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag)) / (n - lag)
    return cov / var
