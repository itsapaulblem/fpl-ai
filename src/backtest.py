"""Phase 10 — Backtest harness.

Replay a past season gameweek by gameweek. At each GW we:
  1. Train ONLY on data available before that GW.
  2. Predict every player's xPoints for the upcoming GW.
  3. Compare predictions against the actual `total_points` they scored.
  4. Pick a top-11 "AI XI" (highest predicted) and sum its actual points.

We compare the AI XI's score against:
  - random XI baseline (sample 11 players uniformly)
  - top-by-form baseline (rank by `total_points_lag1`)

Why this matters for the resume:
  Anyone can train a regressor and report RMSE. A backtest answers the
  question a hiring manager actually cares about: *would this model have
  made me money / won my mini-league?*
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .historical import build_multi_season_training, load_vaastav_season
from .model import TARGET_COL, train_model


# ---------------------------------------------------------------------- #
# Result containers
# ---------------------------------------------------------------------- #
@dataclass
class GameweekResult:
    gw: int
    n_players: int
    rmse: float
    mae: float
    ai_xi_points: float
    form_xi_points: float
    random_xi_points: float
    captain_id: int
    captain_actual_points: float


@dataclass
class BacktestReport:
    season: str
    train_seasons: list[str]
    per_gw: list[GameweekResult] = field(default_factory=list)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.__dict__ for r in self.per_gw])

    def summary(self) -> dict:
        df = self.to_frame()
        if df.empty:
            return {"season": self.season, "n_gws": 0}
        return {
            "season": self.season,
            "train_seasons": list(self.train_seasons),
            "n_gws": int(len(df)),
            "rmse_mean": float(df["rmse"].mean()),
            "mae_mean": float(df["mae"].mean()),
            "ai_xi_total": float(df["ai_xi_points"].sum()),
            "form_xi_total": float(df["form_xi_points"].sum()),
            "random_xi_total": float(df["random_xi_points"].sum()),
            "ai_vs_form_pct": _pct_diff(df["ai_xi_points"].sum(),
                                        df["form_xi_points"].sum()),
            "ai_vs_random_pct": _pct_diff(df["ai_xi_points"].sum(),
                                          df["random_xi_points"].sum()),
            "captain_total": float(df["captain_actual_points"].sum()),
        }


def _pct_diff(a: float, b: float) -> float:
    return float((a - b) / b * 100.0) if b else 0.0


# ---------------------------------------------------------------------- #
# Backtest
# ---------------------------------------------------------------------- #
def _build_test_season_features(season: str) -> pd.DataFrame:
    """Build the engineered training set for one season in isolation."""
    return build_multi_season_training(seasons=[season])


def run_backtest(
    test_season: str,
    train_seasons: Iterable[str],
    start_gw: int = 5,
    end_gw: int = 38,
    rng_seed: int = 0,
) -> BacktestReport:
    """Walk-forward backtest. Train once on `train_seasons`, then for each
    GW in `test_season` predict using lag features that already encode only
    pre-GW data (lags are computed within season, so a row for GW=k only
    sees data from GW<k by construction)."""
    train_df = build_multi_season_training(seasons=list(train_seasons))
    bundle = train_model(train_df)

    test_df = _build_test_season_features(test_season)
    if test_df.empty:
        raise ValueError(f"No data found for test_season={test_season}")

    rng = np.random.default_rng(rng_seed)
    report = BacktestReport(season=test_season, train_seasons=list(train_seasons))
    feature_cols = bundle.features

    for gw in range(start_gw, end_gw + 1):
        gw_rows = test_df[test_df["round"] == gw]
        if gw_rows.empty:
            continue

        X = gw_rows[feature_cols].astype(float).fillna(0.0)
        y_true = gw_rows[TARGET_COL].astype(float).values
        y_pred = bundle.model.predict(X, num_iteration=bundle.model.best_iteration)

        scored = gw_rows.assign(pred=y_pred, actual=y_true).reset_index(drop=True)

        ai_xi = scored.nlargest(11, "pred")
        form_col = "total_points_lag1"
        form_xi = (scored.nlargest(11, form_col)
                   if form_col in scored.columns else ai_xi)
        random_idx = rng.choice(len(scored), size=min(11, len(scored)), replace=False)
        random_xi = scored.iloc[random_idx]

        captain_row = scored.nlargest(1, "pred").iloc[0]

        report.per_gw.append(GameweekResult(
            gw=gw,
            n_players=int(len(scored)),
            rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
            mae=float(mean_absolute_error(y_true, y_pred)),
            ai_xi_points=float(ai_xi["actual"].sum()),
            form_xi_points=float(form_xi["actual"].sum()),
            random_xi_points=float(random_xi["actual"].sum()),
            captain_id=int(captain_row["player_id"]),
            captain_actual_points=float(captain_row["actual"]),
        ))
    return report


# ---------------------------------------------------------------------- #
# Comparison vs FPL average manager
# ---------------------------------------------------------------------- #
def average_manager_points(season: str) -> pd.Series | None:
    """Return per-GW average score (vaastav stores it as `average_entry_score`
    on the events table when available). Falls back to None if not present."""
    try:
        data = load_vaastav_season(season, download_if_missing=False)
    except FileNotFoundError:
        return None
    hist = data["history"]
    # vaastav merged_gw sometimes includes per-GW summary cols
    candidates = [c for c in hist.columns if "average" in c.lower()]
    if not candidates:
        return None
    col = candidates[0]
    return hist.groupby("round")[col].first()


__all__ = [
    "GameweekResult",
    "BacktestReport",
    "run_backtest",
    "average_manager_points",
]
