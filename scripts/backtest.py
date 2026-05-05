"""Run a walk-forward backtest of the xPoints model.

Default: train on 2022-23 + 2023-24, replay 2024-25.

Usage:
    python -m scripts.backtest
    python -m scripts.backtest --test 2024-25 --train 2022-23 2023-24
    python -m scripts.backtest --start-gw 1 --end-gw 38
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.backtest import run_backtest

DEFAULT_TRAIN = ["2022-23", "2023-24"]
DEFAULT_TEST = "2024-25"
OUT_DIR = Path("data/processed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward backtest")
    parser.add_argument("--test", default=DEFAULT_TEST, help="Season to replay")
    parser.add_argument("--train", nargs="+", default=DEFAULT_TRAIN,
                        help="Seasons to train on")
    parser.add_argument("--start-gw", type=int, default=5)
    parser.add_argument("--end-gw", type=int, default=38)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    print(f"[backtest] train={args.train}  test={args.test}  GW {args.start_gw}-{args.end_gw}")
    report = run_backtest(
        test_season=args.test,
        train_seasons=args.train,
        start_gw=args.start_gw,
        end_gw=args.end_gw,
    )

    summary = report.summary()
    print("\n=== Summary ===")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:<22} {v:>10.2f}")
        else:
            print(f"  {k:<22} {v}")

    args.out.mkdir(parents=True, exist_ok=True)
    df = report.to_frame()
    csv_path = args.out / f"backtest_{args.test}.csv"
    json_path = args.out / f"backtest_{args.test}_summary.json"
    df.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(summary, indent=2))
    print(f"\nper-GW results -> {csv_path}")
    print(f"summary        -> {json_path}")


if __name__ == "__main__":
    main()
