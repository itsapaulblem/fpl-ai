"""Phase 5 — LightGBM xPoints model.

Trains a LightGBM regressor that predicts a player's points in the *next*
gameweek. Uses a strict time-based train/validation split (last 4 GWs as
holdout) so we never evaluate on data the model could have memorised.

Key public API:
    train_model(training_df)       -> dict {model, features, metrics, ...}
    save_model(bundle, path)       -> persists with joblib
    load_model(path)               -> reads bundle
    predict_next_gw(bundle, ...)   -> DataFrame ranked by xPoints
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .data_loader import (
    LAG_FEATURES,
    ROLLING_WINDOWS,
    PROCESSED_DIR,
    upcoming_fixtures,
)

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_MODEL_PATH = MODELS_DIR / "xpoints_lgbm.joblib"

HOLDOUT_GWS = 4  # last N finished GWs reserved for validation
TARGET_COL = "target_points"


# Feature selection
def feature_columns(df: pd.DataFrame) -> list[str]:
    """All engineered + static columns the model is allowed to see.

    Strict allowlist: nothing that includes the current GW's outcome.
    """
    lag_cols: list[str] = []
    for f in LAG_FEATURES:
        lag_cols.append(f"{f}_lag1")
        for w in ROLLING_WINDOWS:
            lag_cols.append(f"{f}_roll{w}")

    static = [
        "element_type", "is_home", "opp_strength",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
        "strength_overall_home", "strength_overall_away",
    ]
    cols = [c for c in lag_cols + static if c in df.columns]
    return cols


# Train / validation split
def time_split(
    df: pd.DataFrame, holdout_gws: int = HOLDOUT_GWS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the last `holdout_gws` gameweeks for validation."""
    if df.empty:
        return df, df
    max_gw = int(df["round"].max())
    cutoff = max_gw - holdout_gws
    train = df[df["round"] <= cutoff].copy()
    val = df[df["round"] > cutoff].copy()
    return train, val

# Training
@dataclass
class ModelBundle:
    model: lgb.Booster
    features: list[str]
    metrics: dict[str, float]
    trained_through_gw: int


def train_model(
    training_df: pd.DataFrame,
    holdout_gws: int = HOLDOUT_GWS,
    params: dict | None = None,
    num_boost_round: int = 600,
    early_stopping_rounds: int = 40,
) -> ModelBundle:
    """Train a LightGBM regressor on the engineered training set."""
    if training_df.empty:
        raise ValueError("training_df is empty — fetch + build the data first.")

    features = feature_columns(training_df)
    if not features:
        raise ValueError("No usable feature columns found in training_df.")

    train_df, val_df = time_split(training_df, holdout_gws)
    if val_df.empty:
        # Not enough GWs played yet — fall back to a 90/10 random split.
        val_df = train_df.sample(frac=0.1, random_state=0)
        train_df = train_df.drop(val_df.index)

    X_train = train_df[features].astype(float).fillna(0.0)
    y_train = train_df[TARGET_COL].astype(float).values
    X_val = val_df[features].astype(float).fillna(0.0)
    y_val = val_df[TARGET_COL].astype(float).values

    default_params = {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 5,
        "verbose": -1,
    }
    if params:
        default_params.update(params)

    dtrain = lgb.Dataset(X_train, label=y_train)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    booster = lgb.train(
        default_params,
        dtrain,
        num_boost_round=num_boost_round,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=[
            lgb.early_stopping(early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )

    pred_val = booster.predict(X_val, num_iteration=booster.best_iteration)
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y_val, pred_val))),
        "mae": float(mean_absolute_error(y_val, pred_val)),
        "n_train": int(len(train_df)),
        "n_val": int(len(val_df)),
        "best_iteration": int(booster.best_iteration or num_boost_round),
    }
    trained_through = int(training_df["round"].max())
    return ModelBundle(
        model=booster,
        features=features,
        metrics=metrics,
        trained_through_gw=trained_through,
    )

# Persistence
def save_model(bundle: ModelBundle, path: Path | str = DEFAULT_MODEL_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": bundle.model,
            "features": bundle.features,
            "metrics": bundle.metrics,
            "trained_through_gw": bundle.trained_through_gw,
        },
        path,
    )
    return path


def load_model(path: Path | str = DEFAULT_MODEL_PATH) -> ModelBundle:
    raw = joblib.load(Path(path))
    return ModelBundle(
        model=raw["model"],
        features=raw["features"],
        metrics=raw["metrics"],
        trained_through_gw=raw["trained_through_gw"],
    )

# Inference: rank players for the upcoming gameweek
def feature_importance(bundle: ModelBundle, top: int = 20) -> pd.DataFrame:
    imp = bundle.model.feature_importance(importance_type="gain")
    return (
        pd.DataFrame({"feature": bundle.features, "gain": imp})
        .sort_values("gain", ascending=False)
        .head(top)
        .reset_index(drop=True)
    )


def _latest_lag_row_per_player(history: pd.DataFrame, training_df: pd.DataFrame) -> pd.DataFrame:
    """Take each player's most recent row from the engineered training set —
    its lag features describe what they did up to and including their last GW,
    which is exactly what we want as input for the *next* GW."""
    if training_df.empty:
        return training_df
    latest = (
        training_df.sort_values(["player_id", "round"])
        .groupby("player_id", as_index=False)
        .tail(1)
    )
    return latest


def predict_next_gw(
    bundle: ModelBundle,
    training_df: pd.DataFrame,
    players: pd.DataFrame,
    fixtures: pd.DataFrame,
    next_gw: int,
) -> pd.DataFrame:
    """Predict xPoints for every player in the upcoming gameweek.

    Returns a DataFrame ranked by xPoints with display columns: web_name,
    team_name, position, price, xPoints.
    """
    latest = _latest_lag_row_per_player(training_df, training_df)
    if latest.empty:
        return latest

    # Drop is_home/opp_strength from latest (they describe past match) and
    # replace with the *next* fixture's values.
    drop_cols = [c for c in ("is_home", "opp_strength", "opponent_team", "was_home")
                 if c in latest.columns]
    latest = latest.drop(columns=drop_cols)

    fx = upcoming_fixtures(fixtures, players, next_gw=next_gw, horizon=1)
    fx = fx[fx["event"] == next_gw]
    # Map opponent team -> strength
    opp = (players[["team", "strength"]]
           .drop_duplicates()
           .rename(columns={"team": "opponent", "strength": "opp_strength"}))
    fx = fx.merge(opp, on="opponent", how="left")

    fx_keep = [c for c in ("player_id", "is_home", "opp_strength") if c in fx.columns]
    merged = latest.merge(fx[fx_keep], on="player_id", how="inner")
    if merged.empty:
        return merged

    X = merged[bundle.features].astype(float).fillna(0.0)
    merged["xPoints"] = bundle.model.predict(
        X, num_iteration=bundle.model.best_iteration
    )

    # Only re-merge display columns the merged frame doesn't already have.
    display_cols = ["web_name", "team_name", "team_code", "position", "price"]
    add_cols = [c for c in display_cols if c in players.columns and c not in merged.columns]
    if add_cols:
        merged = merged.merge(
            players[["player_id", *add_cols]], on="player_id", how="left"
        )

    # Double-gameweeks produce one row per fixture — sum xPoints into one row per player.
    group_cols = [c for c in ("player_id", "web_name", "team_name", "team_code", "position", "price", "team")
                  if c in merged.columns]
    agg = (
        merged.groupby(group_cols, as_index=False)
        .agg(xPoints=("xPoints", "sum"),
             is_home=("is_home", "max"),
             opp_strength=("opp_strength", "mean"),
             n_fixtures=("xPoints", "size"))
    )

    cols = ["player_id", "web_name", "team_name", "team_code", "position", "team", "price",
            "n_fixtures", "is_home", "opp_strength", "xPoints"]
    cols = [c for c in cols if c in agg.columns]
    return agg[cols].sort_values("xPoints", ascending=False).reset_index(drop=True)


__all__ = [
    "ModelBundle",
    "DEFAULT_MODEL_PATH",
    "feature_columns",
    "time_split",
    "train_model",
    "save_model",
    "load_model",
    "predict_next_gw",
    "feature_importance",
]
