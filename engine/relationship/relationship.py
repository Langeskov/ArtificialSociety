"""Relationships — the social network between agents (§14).

For the MVP this is a lightweight undirected friendship/influence network seeded
by ideological and personality proximity, stored as an adjacency map. The full
directed relationship model (trade, leadership, conflict) lands in phase 2.
"""

from __future__ import annotations

import random
from typing import Sequence

from ..agent.agent import Agent


def build_network(agents: Sequence[Agent], cfg: dict, rng: random.Random) -> dict[str, list[str]]:
    """Seed a social network: agents connect to ideologically/personality-close
    peers. Returns {agent_id: [neighbor_id, ...]}."""
    rel = cfg.get("relationships", {})
    avg_degree = rel.get("avg_degree", 6)
    network: dict[str, list[str]] = {a.id: [] for a in agents}

    # Sort each agent's potential friends by ideological distance and keep the
    # closest few (plus a couple of random "weak ties").
    ids = [a.id for a in agents]
    for a in agents:
        scored = []
        for b in agents:
            if b is a:
                continue
            d = a.ideology.distance(b.ideology)
            # Personality similarity nudges friendship.
            trust_diff = abs(a.personality["trust"] - b.personality["trust"])
            scored.append((d + trust_diff * 0.3, b.id))
        scored.sort(key=lambda t: t[0])
        k = min(len(scored), avg_degree)
        friends = [sid for _, sid in scored[:k]]
        # A few weak ties across the spectrum.
        if len(scored) > k + 2 and rng.random() < 0.3:
            friends.append(scored[rng.randint(k, len(scored) - 1)][1])
        network[a.id] = friends

    # Make it symmetric.
    for a in agents:
        for fid in network[a.id]:
            if a.id not in network.setdefault(fid, []):
                network[fid].append(a.id)
    return network
