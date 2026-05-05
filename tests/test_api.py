"""Tests for the FastAPI service.

We avoid calling the live FPL API by patching `state` after startup with
synthetic data + a tiny LightGBM model trained on it.
"""
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from src.api import app
from src.data_loader import build_training_set
from src.model import train_model


# ---------------------------------------------------------------------- #
# Synthetic universe — enough players to satisfy ILP + non-trivial signal
# ---------------------------------------------------------------------- #
def _toy_history(n_players: int = 30, n_gws: int = 18) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for pid in range(1, n_players + 1):
        skill = rng.uniform(2, 8)
        prev = 60
        for gw in range(1, n_gws + 1):
            pts = max(0, int(rng.normal(skill * (prev / 90), 2)))
            rows.append({
                "player_id": pid, "round": gw,
                "opponent_team": ((pid + gw) % 6) + 1, "was_home": gw % 2,
                "minutes": prev, "total_points": pts,
                "bps": int(rng.integers(0, 40)),
                "ict_index": float(rng.uniform(0, 20)),
                "expected_goal_involvements": float(rng.uniform(0, 1)),
                "expected_goals_conceded": float(rng.uniform(0, 2)),
                "value": 50,
            })
            prev = int(rng.choice([0, 30, 60, 90], p=[0.1, 0.1, 0.2, 0.6]))
    return pd.DataFrame(rows)


def _toy_players(n_players: int = 30) -> pd.DataFrame:
    positions = ["GKP"] * 6 + ["DEF"] * 12 + ["MID"] * 8 + ["FWD"] * 4
    rng = np.random.default_rng(1)
    rows = []
    for pid in range(1, n_players + 1):
        rows.append({
            "player_id": pid, "team": ((pid - 1) % 6) + 1,
            "element_type": 1, "position": positions[pid - 1],
            "web_name": f"P{pid}", "team_name": f"T{((pid - 1) % 6) + 1}",
            "price": float(rng.uniform(4.0, 12.0)),
            "strength": 3,
            "strength_attack_home": 3, "strength_attack_away": 3,
            "strength_defence_home": 3, "strength_defence_away": 3,
            "strength_overall_home": 3, "strength_overall_away": 3,
        })
    return pd.DataFrame(rows)


def _toy_fixtures(next_gw: int = 19) -> pd.DataFrame:
    rows = []
    for i in range(0, 6, 2):
        rows.append({
            "event": next_gw, "team_h": i + 1, "team_a": i + 2,
            "team_h_difficulty": 3, "team_a_difficulty": 3,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- #
# Fixtures
# ---------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def fake_state():
    """Build a complete fake state once for the module."""
    players = _toy_players()
    history = _toy_history()
    fixtures = _toy_fixtures(next_gw=19)
    training = build_training_set(history, players)
    bundle = train_model(training, holdout_gws=3, num_boost_round=40, early_stopping_rounds=10)
    return {
        "players": players, "history": history, "fixtures": fixtures,
        "training": training, "bundle": bundle,
    }


@pytest.fixture
def client(fake_state):
    """FastAPI TestClient with state pre-populated. Bypasses the lifespan
    (which would hit the real FPL API) by patching load_or_fetch + load_model."""
    fake_boot = {
        "events": [
            {"id": gw, "is_current": gw == 18, "is_next": gw == 19}
            for gw in range(1, 39)
        ],
    }

    class FakeClient:
        def bootstrap(self):
            return fake_boot

        def manager_picks(self, tid, gw):
            # Build a legal 15-man squad from our 30 players
            pos_quotas = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
            picks = []
            for pos, n in pos_quotas.items():
                ids = fake_state["players"][fake_state["players"]["position"] == pos].head(n)["player_id"].tolist()
                picks.extend({"element": int(i)} for i in ids)
            return {"picks": picks}

    with patch.object(api_module, "load_or_fetch") as mock_load, \
         patch.object(api_module, "load_model") as mock_model, \
         patch.object(api_module, "FPLClient", return_value=FakeClient()):
        mock_load.return_value = {
            "players": fake_state["players"],
            "history": fake_state["history"],
            "fixtures": fake_state["fixtures"],
        }
        mock_model.return_value = fake_state["bundle"]
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------- #
# Tests
# ---------------------------------------------------------------------- #
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model_val_rmse" in body
    assert body["n_players"] == 30


def test_gameweek(client):
    r = client.get("/gameweek")
    assert r.status_code == 200
    assert r.json() == {"current": 18, "next": 19}


def test_predictions(client):
    r = client.get("/predictions?top=10")
    assert r.status_code == 200
    body = r.json()
    assert body["gameweek"] == 19
    assert len(body["players"]) <= 10
    # Should be sorted by xPoints descending
    xps = [p["xPoints"] for p in body["players"]]
    assert xps == sorted(xps, reverse=True)


def test_squad(client):
    r = client.get("/squad?budget=120")  # generous budget for synthetic prices
    assert r.status_code == 200
    body = r.json()
    assert len(body["starting_xi"]) == 11
    assert len(body["bench"]) == 4
    assert body["captain_id"] is not None
    assert body["formation"].count("-") == 2


def test_transfers(client):
    r = client.get("/transfers?tid=1&bank=5&free=1&max_transfers=1")
    assert r.status_code == 200
    body = r.json()
    assert body["target_gameweek"] == 19
    assert "baseline" in body
    assert "best" in body
    assert isinstance(body["best_is_no_transfer"], bool)


def test_predictions_invalid_top(client):
    r = client.get("/predictions?top=0")
    assert r.status_code == 422  # validation error from Query(ge=1)
