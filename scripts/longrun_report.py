"""v0.3 长跑验证（§42, §46, §50）：N 个 Society × M 天 × 1000 Agent。

生成政治动力学报告：X/Y/Z 方差、极化度、相关矩阵、簇数、吸引子数、
边界集中、崩溃率、恢复率、平均 tick 性能。
"""
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine
from configs.loader import default_society_config
from engine.politics.observability import (
    polarization_per_axis,
    axis_correlation,
    detect_axis_dominance,
    detect_clusters,
    detect_attractors,
)

SOCIETIES = 10
AGENTS = 1000
DAYS = 30           # 演示长跑（1000 天约 6h，此处 30 天）
SEED_START = 0


def main():
    print(f"=== v0.3 Political Dynamics Long-Run ===", flush=True)
    print(f"{SOCIETIES} societies × {AGENTS} agents × {DAYS} days", flush=True)
    print(flush=True)

    eng = SimulationEngine()
    rows = []
    t0 = time.time()
    total_ticks = 0

    for i in range(SOCIETIES):
        seed = SEED_START + i
        cfg = default_society_config()
        cfg["population"]["count"] = AGENTS
        s = eng.create_society(cfg, seed=seed)

        # 记录温度峰值 / 最终值（判断恢复）
        temp_peak = 0.0
        for _ in range(DAYS):
            eng.step(s.society_id, ticks=100)
            total_ticks += 100
            t = s.metrics()["social_temperature"]
            temp_peak = max(temp_peak, t)

        m = s.metrics()
        pol = polarization_per_axis(s.agents)
        corr = axis_correlation(s.agents)
        clusters = detect_clusters(s.agents, min_size=15)
        attractors = detect_attractors(s.agents, min_size=15)
        dominance = detect_axis_dominance(s.agents)

        recovered = temp_peak > 0.4 and m["social_temperature"] < temp_peak * 0.7
        rows.append({
            "seed": seed,
            "dominance": dominance,
            "x_var": pol["x_variance"], "y_var": pol["y_variance"], "z_var": pol["z_variance"],
            "x_pol": pol["x_polarization"], "y_pol": pol["y_polarization"], "z_pol": pol["z_polarization"],
            "corr_xy": corr["xy"], "corr_xz": corr["xz"], "corr_yz": corr["yz"],
            "clusters": len(clusters), "attractors": len(attractors),
            "boundary": m["boundary_concentration"],
            "temp_final": m["social_temperature"], "temp_peak": temp_peak,
            "recovered": recovered,
            "collapse": m["axis_dominance"] == "X_DOMINANT",  # X 主导 = 退化
        })
        print(f"  [{i+1}/{SOCIETIES}] seed={seed} dom={dominance} "
              f"x_var={pol['x_variance']:.3f} y_var={pol['y_variance']:.3f} z_var={pol['z_variance']:.3f} "
              f"clusters={len(clusters)} bound={m['boundary_concentration']:.3f}", flush=True)

    elapsed = time.time() - t0
    rate = total_ticks / elapsed

    # ---- 汇总报告 ----
    dom_counts = {}
    for r in rows:
        dom_counts[r["dominance"]] = dom_counts.get(r["dominance"], 0) + 1
    n_collapse = sum(1 for r in rows if r["collapse"])
    n_recovered = sum(1 for r in rows if r["recovered"])

    print(f"--- 每 Society 结果 ---")
    print(f"{'seed':>4} {'dominance':>12} {'x_var':>7} {'y_var':>7} {'z_var':>7} "
          f"{'x_pol':>6} {'y_pol':>6} {'z_pol':>6} {'corr_xy':>8} {'clusters':>8} {'attract':>7} {'bound':>6} {'recover':>7}")
    for r in rows:
        print(f"{r['seed']:>4} {r['dominance']:>12} {r['x_var']:>7.3f} {r['y_var']:>7.3f} {r['z_var']:>7.3f} "
              f"{r['x_pol']:>6.2f} {r['y_pol']:>6.2f} {r['z_pol']:>6.2f} {r['corr_xy']:>8.2f} "
              f"{r['clusters']:>8} {r['attractors']:>7} {r['boundary']:>6.3f} {str(r['recovered']):>7}")

    print()
    print(f"--- 汇总 ---")
    print(f"轴主导分布: {dom_counts}")
    print(f"X 主导退化（collapse）: {n_collapse}/{SOCIETIES}")
    print(f"危机后恢复: {n_recovered}/{SOCIETIES}")
    print(f"平均 X 方差: {statistics.mean(r['x_var'] for r in rows):.3f}")
    print(f"平均 Y 方差: {statistics.mean(r['y_var'] for r in rows):.3f}")
    print(f"平均 Z 方差: {statistics.mean(r['z_var'] for r in rows):.3f}")
    print(f"平均簇数: {statistics.mean(r['clusters'] for r in rows):.1f}")
    print(f"平均吸引子数: {statistics.mean(r['attractors'] for r in rows):.1f}")
    print(f"平均边界集中: {statistics.mean(r['boundary'] for r in rows):.3f}")
    print(f"平均 tick 性能: {rate:.1f} ticks/sec（{AGENTS} agents）")
    print(f"总耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
