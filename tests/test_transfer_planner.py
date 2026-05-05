"""Tests for src.transfer_planner — synthetic squads & predictions."""
import pandas as pd
import pytest

from src.transfer_planner import HIT_COST, plan_transfers


def _make_predictions() -> pd.DataFrame:
    """Build a 30-player universe with clear hierarchies of xPoints."""
    rows = []
    pid = 1
    pos_counts = {"GKP": 6, "DEF": 12, "MID": 14, "FWD": 8}
    for pos, n in pos_counts.items():
        for i in range(n):
            rows.append({
                "player_id": pid,
                "web_name": f"P{pid}",
                "team_name": f"T{(pid % 6) + 1}",
                "position": pos,
                "team": (pid % 6) + 1,
                "price": 5.0 + (i * 0.3),       # spread of prices
                "xPoints": 1.0 + i * 0.5,       # higher pid in pos = more xP
            })
            pid += 1
    return pd.DataFrame(rows)


def _build_squad(preds: pd.DataFrame) -> pd.DataFrame:
    """Take the *worst* legal squad: lowest-xP per position. Plenty of room to improve."""
    quotas = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    parts = [preds[preds["position"] == pos].nsmallest(n, "xPoints")
             for pos, n in quotas.items()]
    squad = pd.concat(parts, ignore_index=True).copy()
    # Relax club cap by reassigning teams 1..6 round-robin
    squad["team"] = (squad.index % 6) + 1
    squad["selling_price"] = squad["price"]
    return squad


def test_baseline_is_returned_when_no_transfers_help():
    """With 0 transfers allowed, plans should be empty."""
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep = plan_transfers(squad, preds, bank=10.0, free_transfers=1, max_transfers=0)
    assert rep.plans == []
    assert rep.best() is rep.baseline


def test_one_transfer_finds_an_upgrade():
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep = plan_transfers(squad, preds, bank=20.0, free_transfers=1, max_transfers=1)
    assert len(rep.plans) > 0
    best = rep.best()
    assert best.n_transfers == 1
    assert best.hit_cost == 0  # 1 transfer with 1 free = no hit
    assert best.net_xpoints > rep.baseline.xi_xpoints


def test_hit_cost_is_applied_correctly():
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep = plan_transfers(squad, preds, bank=20.0, free_transfers=0, max_transfers=1)
    if rep.plans:  # if any 1-transfer is worth even after a 4-pt hit
        best = rep.plans[0]
        assert best.hit_cost == HIT_COST
        # net = xi_xp - 4
        assert best.net_xpoints == pytest.approx(best.xi_xpoints - HIT_COST)


def test_two_transfers_can_beat_one():
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep1 = plan_transfers(squad, preds, bank=20.0, free_transfers=2, max_transfers=1)
    rep2 = plan_transfers(squad, preds, bank=20.0, free_transfers=2, max_transfers=2)
    # With 2 free transfers, the 2-transfer search should never be worse
    assert rep2.best().net_xpoints >= rep1.best().net_xpoints - 1e-6


def test_budget_constraint_is_respected():
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep = plan_transfers(squad, preds, bank=0.5, free_transfers=1, max_transfers=2)
    for plan in rep.plans:
        assert plan.bank_after >= -1e-6


def test_resulting_squad_stays_legal():
    preds = _make_predictions()
    squad = _build_squad(preds)
    rep = plan_transfers(squad, preds, bank=20.0, free_transfers=1, max_transfers=2)
    quotas = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    for plan in rep.plans:
        assert len(plan.new_squad) == 15
        counts = plan.new_squad["position"].value_counts().to_dict()
        for pos, n in quotas.items():
            assert counts.get(pos, 0) == n
        assert plan.new_squad["team"].value_counts().max() <= 3
