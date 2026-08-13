"""Storage — SQLite for structured state + JSON event log (§32).

Keeps it dependency-free (stdlib sqlite3 + json). Tables mirror the plan:
societies, agents, agent_states, relationships, groups, events, event_links,
metrics, experiments, model_calls.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "society.sqlite3"
        self.event_log_path = self.data_dir / "events.jsonl"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS societies (
                society_id TEXT PRIMARY KEY, seed INTEGER, status TEXT, config TEXT, created_at REAL
            );
            CREATE TABLE IF NOT EXISTS agents (
                society_id TEXT, agent_id TEXT, snapshot TEXT,
                PRIMARY KEY (society_id, agent_id)
            );
            CREATE TABLE IF NOT EXISTS agent_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                society_id TEXT, agent_id TEXT, tick INTEGER, x REAL, y REAL, z REAL,
                money REAL, food REAL, anger REAL
            );
            CREATE TABLE IF NOT EXISTS relationships (
                society_id TEXT, source TEXT, target TEXT, type TEXT, strength REAL
            );
            CREATE TABLE IF NOT EXISTS groups (
                society_id TEXT, group_id TEXT, leader TEXT, members TEXT, ideology TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                society_id TEXT, event_id TEXT, tick INTEGER, type TEXT, source TEXT,
                severity REAL, effects TEXT, description TEXT, cause_event_id TEXT
            );
            CREATE TABLE IF NOT EXISTS event_links (
                society_id TEXT, cause_event_id TEXT, effect_event_id TEXT
            );
            CREATE TABLE IF NOT EXISTS metrics (
                society_id TEXT, tick INTEGER, metrics TEXT
            );
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY, spec TEXT, society_ids TEXT, created_at REAL
            );
            CREATE TABLE IF NOT EXISTS model_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                society_id TEXT, agent_id TEXT, tick INTEGER, request TEXT, response TEXT
            );
            """
        )
        self._conn.commit()

    def save_society(self, s) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO societies VALUES (?,?,?,?,?)",
                (s.society_id, s.seed, s.status, json.dumps(s.config), s.created_at),
            )
            self._conn.commit()

    def save_agents(self, society_id: str, agents) -> None:
        with self._lock:
            rows = [(society_id, a.id, json.dumps(a.snapshot())) for a in agents]
            self._conn.executemany(
                "INSERT OR REPLACE INTO agents VALUES (?,?,?)", rows
            )
            self._conn.commit()

    def save_agent_state(self, society_id: str, a, tick: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_states (society_id, agent_id, tick, x, y, z, money, food, anger) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    society_id, a.id, tick,
                    a.ideology.x, a.ideology.y, a.ideology.z,
                    a.resources.values.get("money", 0.0),
                    a.resources.values.get("food", 0.0),
                    a.status.get("anger", 0.0),
                ),
            )

    def save_agent_states(self, society_id: str, agents, tick: int) -> None:
        """Batch-persist the ideological position of every agent at a given tick."""
        with self._lock:
            rows = [
                (society_id, a.id, tick, a.ideology.x, a.ideology.y, a.ideology.z,
                 a.resources.values.get("money", 0.0),
                 a.resources.values.get("food", 0.0),
                 a.status.get("anger", 0.0))
                for a in agents if a.alive
            ]
            self._conn.executemany(
                "INSERT INTO agent_states (society_id, agent_id, tick, x, y, z, money, food, anger) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self._conn.commit()

    def save_events(self, society_id: str, events) -> None:
        with self._lock:
            for e in events:
                self._conn.execute(
                    "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                    (society_id, e.event_id, e.tick, e.type, e.source, e.severity,
                     json.dumps(e.effects), e.description, e.cause_event_id),
                )
                if e.cause_event_id:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO event_links VALUES (?,?,?)",
                        (society_id, e.cause_event_id, e.event_id),
                    )
            self._conn.commit()

    def append_event_log(self, society_id: str, events) -> None:
        with self._lock:
            with open(self.event_log_path, "a", encoding="utf-8") as f:
                for e in events:
                    rec = e.as_dict()
                    rec["society_id"] = society_id
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def save_metrics(self, society_id: str, tick: int, metrics: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO metrics VALUES (?,?,?)",
                (society_id, tick, json.dumps(metrics)),
            )
            self._conn.commit()

    def save_experiment(self, exp_id: str, spec: dict, society_ids: list) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?)",
                (exp_id, json.dumps(spec), json.dumps(society_ids), time.time()),
            )
            self._conn.commit()

    def agent_history(self, society_id: str, agent_id: str, limit: int = 500) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT tick, x, y, z, money, food, anger FROM agent_states "
            "WHERE society_id=? AND agent_id=? ORDER BY tick DESC LIMIT ?",
            (society_id, agent_id, limit),
        )
        rows = cur.fetchall()
        return [
            {"tick": r[0], "x": r[1], "y": r[2], "z": r[3],
             "money": r[4], "food": r[5], "anger": r[6]}
            for r in reversed(rows)
        ]

    def agent_histories(self, society_id: str, agent_ids: list[str], limit: int = 500) -> dict:
        """Batch history for a set of agents (one query) — for trajectory mode."""
        result: dict[str, list[dict]] = {aid: [] for aid in agent_ids}
        if not agent_ids:
            return result
        cur = self._conn.cursor()
        placeholders = ",".join("?" * len(agent_ids))
        cur.execute(
            f"SELECT agent_id, tick, x, y, z, money, food, anger FROM agent_states "
            f"WHERE society_id=? AND agent_id IN ({placeholders}) ORDER BY tick",
            [society_id, *agent_ids],
        )
        for row in cur.fetchall():
            aid, tick, x, y, z, money, food, anger = row
            if len(result[aid]) < limit:
                result[aid].append({"tick": tick, "x": x, "y": y, "z": z,
                                    "money": money, "food": food, "anger": anger})
        return result

    def close(self) -> None:
        self._conn.close()
