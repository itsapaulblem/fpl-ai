"""CLI entry point.

Examples:
    python main.py                    # recommend XI for next GW
    python main.py --horizon 3        # plan over next 3 GWs
    python main.py --team-id 123456   # also suggest transfers from your team
"""
from __future__ import annotations

import argparse

from src.recommend import format_report, run_pipeline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FPL AI — pick the best team for the next gameweek.")
    p.add_argument("--horizon", type=int, default=1,
                   help="Number of upcoming gameweeks to optimise over (default: 1).")
    p.add_argument("--budget", type=float, default=100.0,
                   help="Squad budget in £m (default: 100.0).")
    p.add_argument("--team-id", type=int, default=None,
                   help="Your FPL manager id, to receive personalised transfer suggestions.")
    p.add_argument("--no-save", action="store_true",
                   help="Don't persist data/model artifacts to disk.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    result = run_pipeline(
        horizon=args.horizon,
        budget=args.budget,
        current_team_id=args.team_id,
        save_artifacts=not args.no_save,
    )
    print()
    print(format_report(result))


if __name__ == "__main__":
    main()
