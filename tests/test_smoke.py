"""Canonical smoke test — exercises the simulation engine headlessly.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

Covers the MVP closed loop (create → generate → run → drift → events → metrics)
without needing the HTTP server. stdlib only, no extra dependencies.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine          # noqa: E402
from engine.society.society import Society                       # noqa: E402
from engine.agent.generator import generate_population           # noqa: E402
from engine.event.event import EventChain                          # noqa: E402
from configs.loader import default_society_config, load_config    # noqa: E402
from models.external.provider import RuleBasedProvider            # noqa: E402


class TestPopulationGeneration(unittest.TestCase):
    def test_default_config_generates_1000_agents(self):
        cfg = default_society_config()
        cfg["population"]["count"] = 1000
        s = Society(society_id="t1", config=cfg, seed=1)
        self.assertEqual(len(s.agents), 1000)

    def test_ideology_within_unit_cube(self):
        cfg = default_society_config()
        cfg["population"]["count"] = 200
        agents = generate_population(cfg["population"], seed=2)
        for a in agents:
            self.assertTrue(-1.0 <= a.ideology.x <= 1.0)
            self.assertTrue(-1.0 <= a.ideology.y <= 1.0)
            self.assertTrue(-1.0 <= a.ideology.z <= 1.0)

    def test_ideology_distribution_respected(self):
        cfg = default_society_config()
        cfg["population"]["count"] = 500
        cfg["population"]["ideology_distribution"] = {"authoritarian": 1.0}
        agents = generate_population(cfg["population"], seed=3)
        labels = {a.ideology.origin_label for a in agents}
        self.assertEqual(labels, {"authoritarian"})


class TestSimulationRun(unittest.TestCase):
    def setUp(self):
        self.engine = SimulationEngine()
        cfg = default_society_config()
        cfg["population"]["count"] = 500
        self.s = self.engine.create_society(cfg, seed=42)

    def test_step_advances_clock_and_metrics(self):
        summary = self.engine.step(self.s.society_id, ticks=50)
        self.assertEqual(summary["clock"]["tick"], 50)
        m = summary["metrics"]
        self.assertEqual(m["population"], 500)
        self.assertTrue(0.0 <= m["resource_inequality"] <= 1.0)
        self.assertTrue(0.0 <= m["political_polarization"] <= 1.0)

    def test_long_run_produces_events(self):
        for _ in range(30):
            self.engine.step(self.s.society_id, ticks=25)  # 750 ticks
        self.assertGreater(len(self.s.events.events), 0)


class TestEventChain(unittest.TestCase):
    def test_causality_links_registered(self):
        chain = EventChain()
        a = chain.make(1, "protest")
        chain.make(2, "government_response", cause_event_id=a.event_id)
        self.assertEqual(len(chain.links), 1)
        self.assertEqual(chain.links[0], (a.event_id, "event_00002"))
        tree = chain.descendants(a.event_id)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["type"], "government_response")


class TestProvider(unittest.TestCase):
    def test_rule_based_decide_survival(self):
        p = RuleBasedProvider()
        d = p.decide({"resources": {"money": 5, "food": 3}}, "ctx")
        self.assertEqual(d["action"], "seek_resources")

    def test_rule_based_chat_no_llm(self):
        p = RuleBasedProvider()
        self.assertIn("rule-based", p.chat("m", [])["content"])


class TestConfigLoader(unittest.TestCase):
    def test_load_defaults_when_missing(self):
        cfg = load_config(ROOT / "does-not-exist.yaml")
        self.assertEqual(cfg["population"]["count"], 1000)

    def test_deep_merge_override(self):
        cfg = load_config(ROOT / "experiments" / "authoritarian-increase.yaml")
        self.assertAlmostEqual(cfg["population"]["ideology_distribution"]["authoritarian"], 0.45)


if __name__ == "__main__":
    unittest.main(verbosity=2)
