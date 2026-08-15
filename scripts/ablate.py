"""v0.4 消融实验（§66, §67）：Null Model + 逐子系统关闭。

比较 baseline / no_groups / no_identity / no_information / no_behavior / null(全关)，
回答「新机制究竟产生了什么宏观结构」。

用法:
    python scripts/ablate.py --agents 500 --days 50 --seeds 3
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine
from configs.loader import default_society_config
from engine.metrics.social_metrics import group_metrics, fragmentation_score, integration_score, information_metrics
from engine.politics.observability import polarization_per_axis

SCENARIOS = {
    "baseline": [],
    "no_groups": ["groups"],
    "no_identity": ["identity"],
    "no_information": ["information"],
    "no_behavior": ["behavior"],
    "null": ["groups", "identity", "information", "behavior"],
}


def run_scenario(disable: list, agents: int, days: int, seed: int) -> dict:
    cfg = default_society_config()
    cfg["population"]["count"] = agents
    for key in disable:
        cfg.setdefault(key, {})["enabled"] = False
    eng = SimulationEngine()
    s = eng.create_society(cfg, seed=seed)
    for _ in range(days):
        eng.step(s.society_id, ticks=100)
    pol = polarization_per_axis(s.agents)
    return {
        "active_group_count": group_metrics(s)["active_group_count"],
        "avg_group_size": group_metrics(s)["average_group_size"],
        "identity_strength": sum(a.identity.social_identity_strength for a in s.agents if a.alive) / max(1, sum(1 for a in s.agents if a.alive)),
        "fragmentation": fragmentation_score(s),
        "integration": integration_score(s),
        "information_count": information_metrics(s)["information_count"],
        "cascade_count": information_metrics(s)["information_cascade_count"],
        "x_polarization": pol["x_polarization"],
        "y_polarization": pol["y_polarization"],
        "z_polarization": pol["z_polarization"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=500)
    ap.add_argument("--days", type=int, default=50)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    out_dir = ROOT / "artifacts" / "v0.4" / "ablation"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== v0.4 Ablation === agents={args.agents} days={args.days} seeds={args.seeds}", flush=True)
    all_rows = []
    t0 = time.time()
    for name, disable in SCENARIOS.items():
        rows = []
        for seed in range(args.seeds):
            r = run_scenario(disable, args.agents, args.days, seed)
            r["scenario"] = name
            r["seed"] = seed
            rows.append(r)
            all_rows.append(r)
            print(f"  [{name} seed={seed}] groups={r['active_group_count']} avg_size={r['avg_group_size']:.1f} "
                  f"identity={r['identity_strength']:.2f} frag={r['fragmentation']:.2f} integ={r['integration']:.2f} "
                  f"Xpol={r['x_polarization']:.2f} info={r['information_count']}", flush=True)
        (out_dir / f"{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    (out_dir / "all.json").write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
    print(f"\n耗时 {time.time()-t0:.0f}s，结果写入 {out_dir}", flush=True)

    # 汇总表（平均）
    print("\n=== Ablation Comparison (mean) ===")
    print(f"{'Scenario':<14} {'Groups':>6} {'AvgSize':>7} {'Identity':>8} {'Frag':>5} {'Integ':>5} {'Info':>5} {'X Pol':>6}")
    for name in SCENARIOS:
        rows = [r for r in all_rows if r["scenario"] == name]
        def m(k):
            return sum(r[k] for r in rows) / len(rows)
        print(f"{name:<14} {m('active_group_count'):>6.1f} {m('avg_group_size'):>7.1f} {m('identity_strength'):>8.2f} "
              f"{m('fragmentation'):>5.2f} {m('integration'):>5.2f} {m('information_count'):>5.0f} {m('x_polarization'):>6.2f}")


if __name__ == "__main__":
    main()
