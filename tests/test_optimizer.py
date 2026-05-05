"""Tests for src.optimizer — synthetic players, no network."""
import numpy as np
import pandas as pd
import pytest

from src.optimizer import (
    DEFAULT_BUDGET,
    POSITION_QUOTAS,
    pick_starting_xi,
    pick_team,
    select_squad,
)


def _toy_players(seed: int = 0) -> pd.DataFrame:
    """30 players spread across positions and 6 teams."""
    rng = np.random.default_rng(seed)
    rows = []
    pid = 1
    # Provide enough per position to satisfy quotas with margin
    pos_counts = {"GKP": 6, "DEF": 12, "MID": 14, "FWD": 8}
    for pos, n in pos_counts.items():
        for _ in range(n):
            rows.append({
                "player_id": pid,
                "web_name": f"P{pid}",
                "team_name": f"T{(pid % 6) + 1}",
                "position": pos,
                "team": (pid % 6) + 1,                # 6 teams -> easy to satisfy max-3
                "price": float(rng.uniform(4.0, 12.0)),
                "xPoints": float(rng.uniform(0.5, 9.0)),
            })
            pid += 1
    return pd.DataFrame(rows)


def test_select_squad_satisfies_all_constraints():
    squad = select_squad(_toy_players(), budget=DEFAULT_BUDGET)
    # Size
    assert len(squad) == 15
    # Positions
    counts = squad["position"].value_counts().to_dict()
    for pos, n in POSITION_QUOTAS.items():
        assert counts.get(pos, 0) == n
    # Budget
    assert squad["price"].sum() <= DEFAULT_BUDGET + 1e-6
    # Max 3 per club
    assert squad["team"].value_counts().max() <= 3


def test_select_squad_respects_must_include():
    players = _toy_players()
    forced = int(players["player_id"].iloc[0])
    squad = select_squad(players, must_include=[forced])
    assert forced in set(squad["player_id"])


def test_select_squad_respects_must_exclude():
    players = _toy_players()
    excluded = int(players.sort_values("xPoints", ascending=False)["player_id"].iloc[0])
    squad = select_squad(players, must_exclude=[excluded])
    assert excluded not in set(squad["player_id"])


def test_starting_xi_is_legal_formation():
    squad = select_squad(_toy_players())
    xi, bench, formation = pick_starting_xi(squad)
    assert len(xi) == 11
    assert len(bench) == 4
    counts = xi["position"].value_counts().to_dict()
    assert counts["GKP"] == 1
    assert 3 <= counts.get("DEF", 0) <= 5
    assert 2 <= counts.get("MID", 0) <= 5
    assert 1 <= counts.get("FWD", 0) <= 3
    # Formation string format like "4-4-2"
    assert formation.count("-") == 2


def test_pick_team_returns_optimal_captain_and_totals():
    players = _toy_players()
    sel = pick_team(players)
    # Captain = highest-xP starter
    cap_xp = sel.starting_xi[sel.starting_xi["player_id"] == sel.captain_id]["xPoints"].iloc[0]
    assert cap_xp == sel.starting_xi["xPoints"].max()
    # Total xPoints = XI sum + captain (2x means we add captain xP once more)
    expected = float(sel.starting_xi["xPoints"].sum() + cap_xp)
    assert sel.total_xpoints == pytest.approx(expected)


def test_optimizer_beats_random_squad():
    """Sanity check: ILP should outperform a random feasible 15."""
    players = _toy_players(seed=7)
    optimal = pick_team(players)

    rng = np.random.default_rng(0)
    best_random = -1.0
    for _ in range(20):
        picks = []
        for pos, n in POSITION_QUOTAS.items():
            picks.append(players[players["position"] == pos].sample(n, random_state=int(rng.integers(0, 1e6))))
        squad = pd.concat(picks)
        if squad["price"].sum() <= DEFAULT_BUDGET and squad["team"].value_counts().max() <= 3:
            xi, _, _ = pick_starting_xi(squad)
            score = float(xi["xPoints"].sum() + xi["xPoints"].max())
            best_random = max(best_random, score)

    assert optimal.total_xpoints >= best_random


def test_infeasible_budget_raises():
    players = _toy_players()
    with pytest.raises(RuntimeError):
        select_squad(players, budget=10.0)  # impossible
