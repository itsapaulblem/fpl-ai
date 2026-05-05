"""Smoke tests that don't require network access."""
from __future__ import annotations

import pandas as pd

from src.optimizer import pick_squad


def _toy_player_pool() -> pd.DataFrame:
    """Build a synthetic, feasible pool of players for the LP."""
    rows = []
    pid = 0
    # 4 teams, enough players per position
    teams = [(1, "ARS"), (2, "MCI"), (3, "LIV"), (4, "TOT"), (5, "CHE"), (6, "NEW")]
    spec = {"GKP": 6, "DEF": 12, "MID": 12, "FWD": 8}
    for pos, n in spec.items():
        for i in range(n):
            team_id, team_name = teams[i % len(teams)]
            pid += 1
            rows.append({
                "player_id": pid,
                "web_name": f"{pos}{i}",
                "team": team_id,
                "team_name": team_name,
                "position": pos,
                "price": 4.5 + (i % 7) * 0.5,
                "xPoints": 2.0 + (i % 9) * 0.7,
            })
    return pd.DataFrame(rows)


def test_squad_constraints():
    pool = _toy_player_pool()
    res = pick_squad(pool, budget=100.0)
    assert len(res.squad) == 15
    assert len(res.starting_xi) == 11
    assert res.total_cost <= 100.0 + 1e-6
    counts = res.squad["position"].value_counts().to_dict()
    assert counts.get("GKP") == 2
    assert counts.get("DEF") == 5
    assert counts.get("MID") == 5
    assert counts.get("FWD") == 3
    # Max 3 per club
    assert (res.squad["team"].value_counts() <= 3).all()
    # XI position bounds
    xi_counts = res.starting_xi["position"].value_counts().to_dict()
    assert xi_counts.get("GKP") == 1
    assert 3 <= xi_counts.get("DEF", 0) <= 5
    assert 2 <= xi_counts.get("MID", 0) <= 5
    assert 1 <= xi_counts.get("FWD", 0) <= 3
    # Captain + vice exist & differ
    cap = res.starting_xi[res.starting_xi["is_captain"]]
    vice = res.starting_xi[res.starting_xi["is_vice"]]
    assert len(cap) == 1 and len(vice) == 1
    assert cap.iloc[0]["player_id"] != vice.iloc[0]["player_id"]
