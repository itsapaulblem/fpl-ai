"""Train an xPoints (expected points) model and predict next-GW points.

Uses LightGBM gradient boosting. Falls back to scikit-learn's
HistGradientBoostingRegressor if LightGBM isn't installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
    HAS_LGB = True
except Exception:  # pragma: no cover
    HAS_LGB = False
    from sklearn.ensemble import HistGradientBoostingRegressor

from sklearn.metrics import mean_absolute_error, mean_squared_error

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"

FEATURE_COLS_DEFAULT = [
    "minutes_lag1", "minutes_roll3", "minutes_roll5",
    "total_points_lag1", "total_points_roll3", "total_points_roll5",
    "bps_lag1", "bps_roll3", "bps_roll5",
    "ict_index_lag1", "ict_index_roll3", "ict_index_roll5",
    "expected_goal_involvements_lag1", "expected_goal_involvements_roll3",
    "expected_goals_conceded_lag1", "expected_goals_conceded_roll3",
    "is_home", "opp_strength", "element_type",
    "strength_attack_home", "strength_attack_away",
    "strength_defence_home", "strength_defence_away",
]


@dataclass
class TrainResult:
    model: object
    features: list[str]
    mae: float
    rmse: float


def _select_features(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    return [c for c in candidates if c in df.columns]


def train(
    df: pd.DataFrame,
    target: str = "target_points",
    holdout_last_n_gws: int = 4,
) -> TrainResult:
    """Time-based split: train on early GWs, validate on most recent."""
    if "round" not in df.columns:
        raise ValueError("Training frame must contain 'round' column.")
    df = df.dropna(subset=[target]).copy()
    feats = _select_features(df, FEATURE_COLS_DEFAULT)
    df = df.dropna(subset=feats)
    if df.empty:
        raise ValueError("No training rows after dropping NaNs. Need more GW data.")

    max_round = int(df["round"].max())
    split = max_round - holdout_last_n_gws
    train_df = df[df["round"] <= split]
    val_df = df[df["round"] > split]
    if train_df.empty or val_df.empty:
        train_df, val_df = df, df  # tiny dataset (early season)

    X_tr, y_tr = train_df[feats], train_df[target]
    X_val, y_val = val_df[feats], val_df[target]

    if HAS_LGB:
        model = lgb.LGBMRegressor(
            n_estimators=600,
            learning_rate=0.05,
            num_leaves=63,
            min_child_samples=20,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            verbose=-1,
        )
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
    else:
        model = HistGradientBoostingRegressor(
            max_iter=500, learning_rate=0.05, max_depth=8, random_state=42
        )
        model.fit(X_tr, y_tr)

    preds = model.predict(X_val)
    mae = float(mean_absolute_error(y_val, preds))
    rmse = float(np.sqrt(mean_squared_error(y_val, preds)))
    return TrainResult(model=model, features=feats, mae=mae, rmse=rmse)


def save(result: TrainResult, path: Path | None = None) -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = path or (MODEL_DIR / "xpoints.pkl")
    joblib.dump({"model": result.model, "features": result.features}, path)
    return path


def load(path: Path | None = None) -> tuple[object, list[str]]:
    path = path or (MODEL_DIR / "xpoints.pkl")
    obj = joblib.load(path)
    return obj["model"], obj["features"]


def predict_next_gw(
    model,
    features: list[str],
    players: pd.DataFrame,
    history: pd.DataFrame,
    upcoming: pd.DataFrame,
) -> pd.DataFrame:
    """Build the inference frame: latest lagged stats + next fixture, predict points."""
    h = history.copy()
    num_cols = ["minutes", "total_points", "bps", "ict_index",
                "expected_goal_involvements", "expected_goals_conceded"]
    for c in num_cols:
        if c in h.columns:
            h[c] = pd.to_numeric(h[c], errors="coerce")
    h = h.sort_values(["player_id", "round"])

    feats_cols = ["minutes", "total_points", "bps", "ict_index",
                  "expected_goal_involvements", "expected_goals_conceded"]
    feats_cols = [f for f in feats_cols if f in h.columns]

    grp = h.groupby("player_id")
    rows = []
    for pid, g in grp:
        row = {"player_id": pid}
        for f in feats_cols:
            row[f"{f}_lag1"] = g[f].iloc[-1]
            row[f"{f}_roll3"] = g[f].tail(3).mean()
            row[f"{f}_roll5"] = g[f].tail(5).mean()
        rows.append(row)
    lag_df = pd.DataFrame(rows)

    inf = upcoming.merge(lag_df, on="player_id", how="left")

    teams_idx = players[["team", "strength"]].drop_duplicates().rename(
        columns={"team": "opponent", "strength": "opp_strength"}
    )
    inf = inf.merge(teams_idx, on="opponent", how="left")

    # Players without history (no fixtures yet) -> fill with safe defaults
    for f in features:
        if f not in inf.columns:
            inf[f] = 0.0
    inf[features] = inf[features].fillna(0.0)

    inf["xPoints"] = model.predict(inf[features])

    # Aggregate to per-player horizon (sum across multi-GW horizons)
    agg = inf.groupby("player_id", as_index=False).agg(
        xPoints=("xPoints", "sum"),
        n_fixtures=("event", "count"),
    )
    out = players.merge(agg, on="player_id", how="left")
    out["xPoints"] = out["xPoints"].fillna(0.0)
    out["n_fixtures"] = out["n_fixtures"].fillna(0).astype(int)
    return out
