"""Observability — 政治状态空间观测（v0.3 §12–§22）。

提供：X/Y/Z 独立极化度与双峰性、轴相关矩阵、轴主导检测、政治簇检测、
吸引子检测、分布直方图。所有函数为只读分析，低频调用（非逐 tick）。
"""

from __future__ import annotations

import math
from typing import Sequence

from ..agent.agent import Agent


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _variance(vals: list[float]) -> float:
    n = len(vals)
    if n == 0:
        return 0.0
    m = _mean(vals)
    return sum((x - m) ** 2 for x in vals) / n


def _std(vals: list[float]) -> float:
    return math.sqrt(_variance(vals))


def _bimodality_coefficient(vals: list[float]) -> float:
    """双峰系数 BC = (skewness² + 1) / kurtosis。BC > 0.555 → 双峰/均匀，< 0.555 → 单峰。"""
    n = len(vals)
    if n < 4:
        return 0.0
    m = _mean(vals)
    s = _std(vals)
    if s == 0:
        return 0.0
    m3 = sum((x - m) ** 3 for x in vals) / n
    m4 = sum((x - m) ** 4 for x in vals) / n
    skew = m3 / (s ** 3)
    kurt = m4 / (s ** 4)
    return (skew * skew + 1.0) / kurt


def polarization_per_axis(agents: Sequence[Agent]) -> dict:
    """X/Y/Z 各自极化度 + 双峰系数 + 3D 极化（§12, §13）。"""
    alive = [a for a in agents if a.alive]
    xs = [a.ideology.x for a in alive]
    ys = [a.ideology.y for a in alive]
    zs = [a.ideology.z for a in alive]
    # 归一化 std：均匀 [-1,1] 的 std ≈ 0.577
    norm = 0.577
    return {
        "x_polarization": round(_std(xs) / norm, 4),
        "y_polarization": round(_std(ys) / norm, 4),
        "z_polarization": round(_std(zs) / norm, 4),
        "polarization_3d": round((_std(xs) + _std(ys) + _std(zs)) / (3 * norm), 4),
        "x_bimodality": round(_bimodality_coefficient(xs), 4),
        "y_bimodality": round(_bimodality_coefficient(ys), 4),
        "z_bimodality": round(_bimodality_coefficient(zs), 4),
        "x_variance": round(_variance(xs), 6),
        "y_variance": round(_variance(ys), 6),
        "z_variance": round(_variance(zs), 6),
    }


def axis_correlation(agents: Sequence[Agent]) -> dict:
    """X/Y/Z 皮尔逊相关矩阵（§16）。"""
    alive = [a for a in agents if a.alive]
    xs = [a.ideology.x for a in alive]
    ys = [a.ideology.y for a in alive]
    zs = [a.ideology.z for a in alive]

    def corr(a: list[float], b: list[float]) -> float:
        n = len(a)
        if n < 2:
            return 0.0
        ma, mb = _mean(a), _mean(b)
        cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n
        sa, sb = _std(a), _std(b)
        if sa == 0 or sb == 0:
            return 0.0
        return round(cov / (sa * sb), 4)

    return {
        "xy": corr(xs, ys),
        "xz": corr(xs, zs),
        "yz": corr(ys, zs),
    }


def detect_axis_dominance(agents: Sequence[Agent], var_threshold: float = 0.02) -> str:
    """检测哪个轴占主导（§15）：X_DOMINANT / Y_DOMINANT / Z_DOMINANT / 3D_DYNAMICS / STATIC。"""
    pol = polarization_per_axis(agents)
    vx, vy, vz = pol["x_variance"], pol["y_variance"], pol["z_variance"]
    high = var_threshold
    active = [vx >= high, vy >= high, vz >= high]
    n_active = sum(active)
    if n_active >= 2:
        return "3D_DYNAMICS"
    if n_active == 0:
        return "STATIC"
    if active[0]:
        return "X_DOMINANT"
    if active[1]:
        return "Y_DOMINANT"
    return "Z_DOMINANT"


def detect_clusters(agents: Sequence[Agent], radius: float = 0.35, min_size: int = 10) -> list[dict]:
    """贪心密度聚类（§14）：返回簇中心 + 人口比例。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        return []
    remaining = set(a.id for a in alive)
    clusters = []
    by_id = {a.id: a for a in alive}

    while remaining:
        best, best_density = None, -1
        for a in alive:
            if a.id not in remaining:
                continue
            density = sum(
                1 for b in alive if b.id in remaining and a.ideology.distance(b.ideology) < radius
            )
            if density > best_density:
                best_density, best = density, a
        if best is None or best_density < min_size:
            break
        members = [b for b in alive if b.id in remaining and best.ideology.distance(b.ideology) < radius]
        if len(members) < min_size:
            break
        xs = [m.ideology.x for m in members]
        ys = [m.ideology.y for m in members]
        zs = [m.ideology.z for m in members]
        clusters.append({
            "center": (round(_mean(xs), 3), round(_mean(ys), 3), round(_mean(zs), 3)),
            "population": len(members),
            "ratio": round(len(members) / n, 4),
        })
        for m in members:
            remaining.discard(m.id)
    clusters.sort(key=lambda c: -c["population"])
    return clusters


def detect_attractors(agents: Sequence[Agent], radius: float = 0.35, min_size: int = 10) -> list[dict]:
    """吸引子检测（§21）：簇 + 平均速度幅值（低速 = 已沉降的吸引子）。"""
    alive = [a for a in agents if a.alive]
    by_id = {a.id: a for a in alive}
    clusters = detect_clusters(agents, radius, min_size)
    attractors = []
    for c in clusters:
        cx, cy, cz = c["center"]
        # 该簇中心的平均速度幅值
        members = [a for a in alive if abs(a.ideology.x - cx) < radius and abs(a.ideology.y - cy) < radius and abs(a.ideology.z - cz) < radius]
        speeds = [
            math.sqrt(a.political_velocity[0] ** 2 + a.political_velocity[1] ** 2 + a.political_velocity[2] ** 2)
            for a in members
        ]
        avg_speed = _mean(speeds) if speeds else 0.0
        attractors.append({
            "center": c["center"],
            "population": c["population"],
            "ratio": c["ratio"],
            "avg_speed": round(avg_speed, 5),
            "is_settled": avg_speed < 0.005,
        })
    return attractors


def distribution_histogram(agents: Sequence[Agent], axis: str = "x", bins: int = 20) -> dict:
    """X/Y/Z 分布直方图（§18）。返回 bin 边界 + 计数。"""
    alive = [a for a in agents if a.alive]
    vals = [getattr(a.ideology, axis) for a in alive]
    if not vals:
        return {"bins": [], "counts": []}
    lo, hi = -1.0, 1.0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = int((v - lo) / width)
        idx = max(0, min(bins - 1, idx))
        counts[idx] += 1
    return {
        "bins": [round(lo + i * width, 3) for i in range(bins)],
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# v0.3.1 校准诊断（§16–§21, §30–§32）
# ---------------------------------------------------------------------------

def axis_mean(agents: Sequence[Agent]) -> dict:
    """三轴均值（§20）：区分「整体漂移」与「极化」。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        return {"x_mean": 0.0, "y_mean": 0.0, "z_mean": 0.0}
    return {
        "x_mean": round(sum(a.ideology.x for a in alive) / n, 6),
        "y_mean": round(sum(a.ideology.y for a in alive) / n, 6),
        "z_mean": round(sum(a.ideology.z for a in alive) / n, 6),
    }


def axis_velocity(agents: Sequence[Agent]) -> dict:
    """三轴平均速度 / 平均绝对速度（§18 漂移检测）。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        return {
            "x_drift": 0.0, "y_drift": 0.0, "z_drift": 0.0,
            "x_abs_velocity": 0.0, "y_abs_velocity": 0.0, "z_abs_velocity": 0.0,
        }
    vx = sum(a.political_velocity[0] for a in alive) / n
    vy = sum(a.political_velocity[1] for a in alive) / n
    vz = sum(a.political_velocity[2] for a in alive) / n
    ax_ = sum(abs(a.political_velocity[0]) for a in alive) / n
    ay_ = sum(abs(a.political_velocity[1]) for a in alive) / n
    az_ = sum(abs(a.political_velocity[2]) for a in alive) / n
    return {
        "x_drift": round(vx, 6), "y_drift": round(vy, 6), "z_drift": round(vz, 6),
        "x_abs_velocity": round(ax_, 6), "y_abs_velocity": round(ay_, 6), "z_abs_velocity": round(az_, 6),
    }


def boundary_per_direction(agents: Sequence[Agent], threshold: float = 0.9) -> dict:
    """六方向边界集中（§30）：每个边界人口占比，而非「靠近任意边界」。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        return {k: 0.0 for k in ("x_neg", "x_pos", "y_neg", "y_pos", "z_neg", "z_pos")}
    r = lambda cond: sum(1 for a in alive if cond(a)) / n
    return {
        "x_neg": round(r(lambda a: a.ideology.x < -threshold), 4),
        "x_pos": round(r(lambda a: a.ideology.x > threshold), 4),
        "y_neg": round(r(lambda a: a.ideology.y < -threshold), 4),
        "y_pos": round(r(lambda a: a.ideology.y > threshold), 4),
        "z_neg": round(r(lambda a: a.ideology.z < -threshold), 4),
        "z_pos": round(r(lambda a: a.ideology.z > threshold), 4),
    }


def classify_distribution(vals: list[float], boundary_threshold: float = 0.9) -> str:
    """分布形态分类（§31）：single_peak / two_peak / multi_peak / boundary_accumulation / uniform。"""
    n = len(vals)
    if n == 0:
        return "empty"
    # 边界累积：大量人口压在边界
    boundary_ratio = sum(1 for v in vals if abs(v) > boundary_threshold) / n
    if boundary_ratio > 0.3:
        return "boundary_accumulation"
    bc = _bimodality_coefficient(vals)
    if bc > 0.8:
        return "two_peak"
    if bc > 0.6:
        return "multi_peak"
    # 均匀：std 接近均匀分布 0.577 且低双峰
    s = _std(vals)
    if s > 0.45 and bc < 0.55:
        return "uniform"
    return "single_peak"


def classify_axes(agents: Sequence[Agent]) -> dict:
    """三轴分布形态（§31）。"""
    alive = [a for a in agents if a.alive]
    return {
        "x_shape": classify_distribution([a.ideology.x for a in alive]),
        "y_shape": classify_distribution([a.ideology.y for a in alive]),
        "z_shape": classify_distribution([a.ideology.z for a in alive]),
    }


def axis_dominance_force(agents: Sequence[Agent], ratio: float = 1.6) -> str:
    """基于力/速度的主导轴检测（§17）：X_DOMINANT / Y_DOMINANT / Z_DOMINANT / BALANCED。

    用平均绝对速度（真实运动）判断，而非只依据坐标方差（§19 区分平移与极化）。
    """
    v = axis_velocity(agents)
    mags = [v["x_abs_velocity"], v["y_abs_velocity"], v["z_abs_velocity"]]
    total = sum(mags)
    if total < 1e-6:
        return "BALANCED"
    shares = [m / total for m in mags]
    mx = max(shares)
    if mx < 0.5:
        return "BALANCED"
    # 最强轴是否显著超过次强轴
    ordered = sorted(shares, reverse=True)
    if ordered[0] > ordered[1] * ratio and ordered[0] > 0.45:
        idx = shares.index(ordered[0])
        return ("X_DOMINANT", "Y_DOMINANT", "Z_DOMINANT")[idx]
    return "BALANCED"


def force_budget(agents: Sequence[Agent]) -> dict:
    """人口级力预算（§16, §28）：各来源在三轴的平均绝对贡献。"""
    sources = ("economic", "authority", "community", "event", "social", "anchor", "center", "coupling", "noise")
    sums = {ax: {src: 0.0 for src in sources} for ax in "xyz"}
    count = 0
    for a in agents:
        if not a.alive or not a.last_forces:
            continue
        count += 1
        for ax in "xyz":
            for src in sources:
                sums[ax][src] += abs(a.last_forces[ax].get(src, 0.0))
    if count == 0:
        return {ax: {src: 0.0 for src in sources} for ax in "xyz"}
    return {ax: {src: round(sums[ax][src] / count, 6) for src in sources} for ax in "xyz"}


def force_budget_percent(agents: Sequence[Agent]) -> dict:
    """力预算百分比（§28）：各来源占该轴总力比例。"""
    budget = force_budget(agents)
    pct = {}
    for ax in "xyz":
        total = sum(budget[ax].values())
        pct[ax] = {src: round(budget[ax][src] / total * 100, 1) if total > 0 else 0.0 for src in budget[ax]}
    return pct
