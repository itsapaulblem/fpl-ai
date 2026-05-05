"""Train the LightGBM xPoints model on cached FPL data.

Usage:
    python -m scripts.train_model
    python -m scripts.train_model --refresh   # re-download data first
"""
import argparse

from src.data_loader import build_training_set, load_or_fetch
from src.model import (
    DEFAULT_MODEL_PATH,
    feature_importance,
    save_model,
    train_model,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--holdout", type=int, default=4,
                   help="Number of most-recent GWs reserved for validation.")
    args = p.parse_args()

    print("Loading data...")
    data = load_or_fetch(refresh=args.refresh)
    train = build_training_set(data["history"], data["players"])
    print(f"  training rows: {len(train)}  through GW {int(train['round'].max())}")

    print("\nTraining LightGBM...")
    bundle = train_model(train, holdout_gws=args.holdout)
    print(f"  features: {len(bundle.features)}")
    print(f"  best_iter: {bundle.metrics['best_iteration']}")
    print(f"  validation RMSE: {bundle.metrics['rmse']:.3f}")
    print(f"  validation MAE:  {bundle.metrics['mae']:.3f}")
    print(f"  n_train={bundle.metrics['n_train']}  n_val={bundle.metrics['n_val']}")

    print("\nTop 15 features by gain:")
    print(feature_importance(bundle, top=15).to_string(index=False))

    out = save_model(bundle)
    print(f"\nSaved model -> {out}")


if __name__ == "__main__":
    main()
