"""Train the LightGBM xPoints model on multiple historical seasons.

Combines vaastav historical data with the current cached season, then runs
the same `train_model` pipeline. Saves the bundle to a separate path so
you can A/B compare against the single-season model.

Usage:
    python -m scripts.train_multi_season
    python -m scripts.train_multi_season --seasons 2023-24 2024-25
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.data_loader import load_or_fetch
from src.fpl_api import FPLClient
from src.historical import build_multi_season_training
from src.model import MODELS_DIR, save_model, train_model

DEFAULT_SEASONS = ["2022-23", "2023-24", "2024-25"]
DEFAULT_OUT = MODELS_DIR / "xpoints_lgbm_multi.joblib"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train xPoints model on multi-season data")
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS,
                        help="Historical seasons to include")
    parser.add_argument("--no-current", action="store_true",
                        help="Skip the current cached season (historical only)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="Output joblib path")
    args = parser.parse_args()

    cur_history = cur_players = None
    if not args.no_current:
        print("[load] current season cache ...", flush=True)
        bundle = load_or_fetch(FPLClient())
        cur_history = bundle["history"]
        cur_players = bundle["players"]
        print(f"        current rows: {len(cur_history):,}")

    print(f"[load] historical seasons: {', '.join(args.seasons)} ...", flush=True)
    training = build_multi_season_training(
        seasons=args.seasons,
        current_history=cur_history,
        current_players=cur_players,
    )
    print(f"        combined training rows: {len(training):,}")
    print(f"        per-season counts:")
    print(training.groupby("season").size().to_string())

    print("[train] LightGBM ...", flush=True)
    model_bundle = train_model(training)
    print(f"        n_features: {len(model_bundle.features)}")
    print(f"        metrics: {model_bundle.metrics}")

    out = save_model(model_bundle, args.out)
    print(f"[save] {out}")


if __name__ == "__main__":
    main()
