"""Manual data refresh — fetch FPL API data and cache to data/processed/.

Usage:
    python -m scripts.refresh_data            # uses cache if present
    python -m scripts.refresh_data --refresh  # forces re-download
"""
import argparse

from src.data_loader import build_training_set, load_or_fetch


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true",
                   help="Force re-download instead of using cache.")
    p.add_argument("--limit", type=int, default=None,
                   help="Only fetch first N players (for fast testing).")
    args = p.parse_args()

    print("Loading data (this is slow on a fresh run — ~600 API calls)...")
    data = load_or_fetch(refresh=args.refresh)
    players, history, fixtures = data["players"], data["history"], data["fixtures"]
    print(f"  players:  {len(players):>5} rows  ({players.shape[1]} cols)")
    print(f"  history:  {len(history):>5} rows  (one per player-GW)")
    print(f"  fixtures: {len(fixtures):>5} rows")

    print("\nBuilding training set...")
    train = build_training_set(history, players)
    print(f"  training rows: {len(train):>5}")
    print(f"  features (sample): {[c for c in train.columns if c.endswith('_lag1') or c.endswith('_roll3')][:6]}")
    print(f"  target column: 'target_points'  (mean={train['target_points'].mean():.2f})")

    print("\nTop 10 scoring rows in the training set:")
    cols = ["player_id", "round", "is_home", "opp_strength",
            "total_points_lag1", "total_points_roll3", "target_points"]
    cols = [c for c in cols if c in train.columns]
    print(train.nlargest(10, "target_points")[cols].to_string(index=False))


if __name__ == "__main__":
    main()
