"""Recommend the best FPL squad for the upcoming gameweek.

Pipeline:  cached data → trained model → predict xPoints → ILP optimizer.

Usage:
    python -m scripts.recommend_team
    python -m scripts.recommend_team --budget 100 --gw 36
"""
import argparse

from src.data_loader import build_training_set, load_or_fetch
from src.fpl_api import FPLClient, next_gameweek
from src.model import DEFAULT_MODEL_PATH, load_model, predict_next_gw
from src.optimizer import format_team, pick_team


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--budget", type=float, default=100.0)
    p.add_argument("--gw", type=int, default=None,
                   help="Target gameweek (defaults to next).")
    p.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    p.add_argument("--refresh", action="store_true",
                   help="Re-download data instead of using cache.")
    args = p.parse_args()

    print("Loading data + model...")
    data = load_or_fetch(refresh=args.refresh)
    players, history, fixtures = data["players"], data["history"], data["fixtures"]

    if args.gw is None:
        args.gw = next_gameweek(FPLClient().bootstrap())
    print(f"  target gameweek: GW{args.gw}")

    bundle = load_model(args.model)
    print(f"  model trained through GW{bundle.trained_through_gw}  "
          f"(val RMSE={bundle.metrics['rmse']:.3f})")

    train = build_training_set(history, players)
    preds = predict_next_gw(bundle, train, players, fixtures, next_gw=args.gw)
    print(f"  predicted {len(preds)} players")

    print("\nTop 10 by xPoints:")
    show_cols = [c for c in ("web_name", "team_name", "position", "price",
                             "n_fixtures", "is_home", "opp_strength", "xPoints")
                 if c in preds.columns]
    rename_map = {"web_name": "player", "team_name": "team", "opp_strength": "opp_str"}
    print(preds.head(10)[show_cols].rename(columns=rename_map).to_string(index=False))

    print("\nOptimising squad...")
    sel = pick_team(preds, budget=args.budget)

    print()
    print(format_team(sel))


if __name__ == "__main__":
    main()
