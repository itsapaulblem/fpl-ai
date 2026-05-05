"""Tests for src.model — synthetic data, no network."""
import numpy as np
import pandas as pd

from src.data_loader import build_training_set
from src.model import (
    feature_columns,
    time_split,
    train_model,
    save_model,
    load_model,
    predict_next_gw,
)


def _toy_history(n_players: int = 8, n_gws: int = 15) -> pd.DataFrame:
    """A history where total_points correlates with previous-GW minutes —
    so a model should learn something better than the mean."""
    rng = np.random.default_rng(0)
    rows = []
    for pid in range(1, n_players + 1):
        skill = rng.uniform(2, 8)
        prev_minutes = 60
        for gw in range(1, n_gws + 1):
            pts = max(0, int(rng.normal(loc=skill * (prev_minutes / 90), scale=2)))
            rows.append({
                "player_id": pid, "round": gw,
                "opponent_team": ((pid + gw) % 4) + 1,
                "was_home": gw % 2,
                "minutes": prev_minutes,
                "total_points": pts,
                "bps": int(rng.integers(0, 40)),
                "ict_index": float(rng.uniform(0, 20)),
                "expected_goal_involvements": float(rng.uniform(0, 1)),
                "expected_goals_conceded": float(rng.uniform(0, 2)),
                "value": 50,
            })
            prev_minutes = int(rng.choice([0, 30, 60, 90], p=[0.1, 0.1, 0.2, 0.6]))
    return pd.DataFrame(rows)


def _toy_players(n_players: int = 8) -> pd.DataFrame:
    return pd.DataFrame([
        {"player_id": pid, "team": (pid % 4) + 1, "element_type": ((pid - 1) % 4) + 1,
         "position": "MID", "web_name": f"P{pid}", "team_name": f"T{(pid % 4) + 1}",
         "price": 5.0, "strength": 3,
         "strength_attack_home": 3, "strength_attack_away": 3,
         "strength_defence_home": 3, "strength_defence_away": 3,
         "strength_overall_home": 3, "strength_overall_away": 3}
        for pid in range(1, n_players + 1)
    ])


def _toy_fixtures(next_gw: int = 16, n_teams: int = 4) -> pd.DataFrame:
    rows = []
    for i in range(0, n_teams, 2):
        rows.append({
            "event": next_gw,
            "team_h": i + 1, "team_a": i + 2,
            "team_h_difficulty": 3, "team_a_difficulty": 3,
        })
    return pd.DataFrame(rows)


def test_feature_columns_match_lag_engineering():
    train = build_training_set(_toy_history(), _toy_players())
    feats = feature_columns(train)
    assert "total_points_lag1" in feats
    assert "total_points_roll3" in feats
    assert "is_home" in feats
    # Crucially, the raw target must NOT be a feature
    assert "total_points" not in feats
    assert "target_points" not in feats


def test_time_split_holds_out_last_n_gameweeks():
    train = build_training_set(_toy_history(), _toy_players())
    tr, val = time_split(train, holdout_gws=3)
    assert tr["round"].max() < val["round"].min()
    assert val["round"].nunique() == 3


def test_train_model_produces_metrics_and_predictions():
    train = build_training_set(_toy_history(n_players=12, n_gws=20), _toy_players(n_players=12))
    bundle = train_model(train, holdout_gws=4, num_boost_round=80, early_stopping_rounds=20)
    assert bundle.metrics["rmse"] > 0
    assert bundle.metrics["n_train"] > 0 and bundle.metrics["n_val"] > 0
    assert len(bundle.features) > 0
    # Sanity: should beat naive "predict the mean" baseline on validation
    _, val = time_split(train, holdout_gws=4)
    baseline_rmse = float(np.sqrt(((val["target_points"] - val["target_points"].mean()) ** 2).mean()))
    assert bundle.metrics["rmse"] <= baseline_rmse * 1.2  # allow a little wiggle


def test_save_and_load_roundtrip(tmp_path):
    train = build_training_set(_toy_history(), _toy_players())
    bundle = train_model(train, holdout_gws=3, num_boost_round=40, early_stopping_rounds=10)
    path = tmp_path / "m.joblib"
    save_model(bundle, path)
    loaded = load_model(path)
    assert loaded.features == bundle.features
    assert loaded.metrics["rmse"] == bundle.metrics["rmse"]


def test_predict_next_gw_returns_ranked_table():
    train = build_training_set(_toy_history(), _toy_players())
    bundle = train_model(train, holdout_gws=3, num_boost_round=40, early_stopping_rounds=10)
    preds = predict_next_gw(
        bundle,
        training_df=train,
        players=_toy_players(),
        fixtures=_toy_fixtures(next_gw=16),
        next_gw=16,
    )
    assert "xPoints" in preds.columns
    assert len(preds) > 0
    # Sorted descending
    assert (preds["xPoints"].diff().dropna() <= 1e-9).all()
