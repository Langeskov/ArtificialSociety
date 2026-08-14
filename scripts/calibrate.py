"""v0.3.1 校准矩阵（§35, §36, §42）：多场景 × 多种子 × 多天。

输出各场景的 X/Y/Z drift、variance、polarization、boundary concentration、
force budget，以及 no_events 场景的 mean_z(t) 轨迹。结果写入
artifacts/v0.3.1/calibration/ 与 artifacts/v0.3.1/baseline/。

用法:
    python scripts/calibrate.py --agents 1000 --days 100 --seeds 5
"""

import argparse
import json
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
    force_budget_percent,
    detect_clusters,
)


def _scenario_config(name: str) -> dict:
    cfg = default_society_config()
    if name == "no_events":
        cfg["events"]["frequency"] = 0.0
    elif name == "no_social":
        cfg["social"]["influence_strength"] = 0.0
        cfg["politics"]["z_axis"]["group_pressure_strength"] = 0.0
    elif name == "no_anchor":
        cfg["politics"]["ideology_anchor_strength"] = 0.0
    elif name == "no_coupling":
        cfg["politics"]["coupling"] = {"mode": "velocity", "xy": 0.0, "xz": 0.0, "yx": 0.0, "yz": 0.0, "zx": 0.0, "zy": 0.0}
    elif name == "balanced_personality":
        cfg["population"]["personality_distribution"] = {
            d: {"high": 0.0, "neutral": 1.0, "low": 0.0}
            for d in ("openness", "conscientiousness", "extraversion", "agreeableness",
                      "neuroticism", "risk_tolerance", "trust", "aggression", "empathy", "authority_preference")
        }
    elif name == "balanced_resources":
        cfg["population"]["initial_resources"] = {
            "money": {"mean": 500, "sigma": 0}, "food": {"mean": 100, "sigma": 0},
            "energy": {"mean": 80, "sigma": 0}, "property": {"mean": 200, "sigma": 0},
            "influence": {"mean": 5, "sigma": 0}, "information": {"mean": 20, "sigma": 0},
        }
    return cfg


def run_scenario(name: str, agents: int, days: int, seed: int):
    cfg = _scenario_config(name)
    cfg["population"]["count"] = agents
    eng = SimulationEngine()
    s = eng.create_society(cfg, seed=seed)

    x0 = statistics.mean(a.ideology.x for a in s.agents)
    y0 = statistics.mean(a.ideology.y for a in s.agents)
    z0 = statistics.mean(a.ideology.z for a in s.agents)

    mean_z_traj = [z0]
    total_ticks = days * 100

    for _ in range(days):
        eng.step(s.society_id, ticks=100)
        if name == "no_events":
            mean_z_traj.append(statistics.mean(a.ideology.z for a in s.agents))

    m = s.metrics()
    pol = polarization_per_axis(s.agents)
    corr = axis_correlation(s.agents)
    clusters = detect_clusters(s.agents, min_size=15)

    x1 = m["x_mean"]; y1 = m["y_mean"]; z1 = m["z_mean"]
    drift = {
        "x": (x1 - x0) / total_ticks,
        "y": (y1 - y0) / total_ticks,
        "z": (z1 - z0) / total_ticks,
    }
    return {
        "scenario": name,
        "seed": seed,
        "x_drift": round(drift["x"], 6), "y_drift": round(drift["y"], 6), "z_drift": round(drift["z"], 6),
        "x_mean": round(x1, 4), "y_mean": round(y1, 4), "z_mean": round(z1, 4),
        "x_var": pol["x_variance"], "y_var": pol["y_variance"], "z_var": pol["z_variance"],
        "x_pol": pol["x_polarization"], "y_pol": pol["y_polarization"], "z_pol": pol["z_polarization"],
        "x_shape": m["x_shape"], "y_shape": m["y_shape"], "z_shape": m["z_shape"],
        "boundary_x_neg": m["boundary_x_neg"], "boundary_x_pos": m["boundary_x_pos"],
        "boundary_y_neg": m["boundary_y_neg"], "boundary_y_pos": m["boundary_y_pos"],
        "boundary_z_neg": m["boundary_z_neg"], "boundary_z_pos": m["boundary_z_pos"],
        "corr_xy": corr["xy"], "corr_xz": corr["xz"], "corr_yz": corr["yz"],
        "clusters": len(clusters),
        "dominance_force": m["axis_dominance_force"],
        "force_budget_pct": force_budget_percent(s.agents),
        "mean_z_traj": [round(v, 4) for v in mean_z_traj] if name == "no_events" else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=1000)
    ap.add_argument("--days", type=int, default=100)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--scenarios", type=str, default="baseline,no_events,no_social,no_anchor,no_coupling")
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(",")]
    out_dir = ROOT / "artifacts" / "v0.3.1" / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== v0.3.1 Calibration Matrix ===", flush=True)
    print(f"scenarios={scenarios} agents={args.agents} days={args.days} seeds={args.seeds}", flush=True)

    rows = []
    t0 = time.time()
    for sc in scenarios:
        sc_rows = []
        for seed in range(args.seeds):
            r = run_scenario(sc, args.agents, args.days, seed)
            sc_rows.append(r)
            rows.append(r)
            print(f"  [{sc} seed={seed}] X drift={r['x_drift']:.4f} Y drift={r['y_drift']:.4f} Z drift={r['z_drift']:.4f} "
                  f"| X var={r['x_var']:.3f} Y var={r['y_var']:.3f} Z var={r['z_var']:.3f} "
                  f"| X pol={r['x_pol']:.2f} Y pol={r['y_pol']:.2f} Z pol={r['z_pol']:.2f} "
                  f"| shape={r['x_shape']}/{r['y_shape']}/{r['z_shape']}", flush=True)
        # 场景汇总（平均）
        agg = {
            "scenario": sc,
            "x_drift": statistics.mean(r["x_drift"] for r in sc_rows),
            "y_drift": statistics.mean(r["y_drift"] for r in sc_rows),
            "z_drift": statistics.mean(r["z_drift"] for r in sc_rows),
            "x_var": statistics.mean(r["x_var"] for r in sc_rows),
            "y_var": statistics.mean(r["y_var"] for r in sc_rows),
            "z_var": statistics.mean(r["z_var"] for r in sc_rows),
            "x_pol": statistics.mean(r["x_pol"] for r in sc_rows),
            "y_pol": statistics.mean(r["y_pol"] for r in sc_rows),
            "z_pol": statistics.mean(r["z_pol"] for r in sc_rows),
        }
        (out_dir / f"{sc}_summary.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
        (out_dir / f"{sc}_raw.json").write_text(json.dumps(sc_rows, indent=2, ensure_ascii=False), encoding="utf-8")

    (out_dir / "all_raw.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\n总耗时 {elapsed:.0f}s，结果写入 {out_dir}", flush=True)

    # 最终校准表（§36）
    print("\n=== Calibration Table ===")
    print(f"{'Scenario':<20} {'X Drift':>9} {'Y Drift':>9} {'Z Drift':>9} {'X Var':>7} {'Y Var':>7} {'Z Var':>7} {'X Pol':>6} {'Y Pol':>6} {'Z Pol':>6}")
    for sc in scenarios:
        sc_rows = [r for r in rows if r["scenario"] == sc]
        def m(k):
            return statistics.mean(r[k] for r in sc_rows)
        print(f"{sc:<20} {m('x_drift'):>9.5f} {m('y_drift'):>9.5f} {m('z_drift'):>9.5f} "
              f"{m('x_var'):>7.3f} {m('y_var'):>7.3f} {m('z_var'):>7.3f} "
              f"{m('x_pol'):>6.2f} {m('y_pol'):>6.2f} {m('z_pol'):>6.2f}")


if __name__ == "__main__":
    main()
