"""Recommend transfers for an existing FPL team.

Usage:
    python -m scripts.recommend_transfers --tid 271610
    python -m scripts.recommend_transfers --tid 271610 --bank 1.5 --free 2
"""
import argparse

import pandas as pd

from src.data_loader import build_training_set, load_or_fetch
from src.fpl_api import FPLClient, current_gameweek, next_gameweek
from src.model import DEFAULT_MODEL_PATH, load_model, predict_next_gw
from src.transfer_planner import format_report, plan_transfers


def fetch_current_squad(client: FPLClient, tid: int, gw: int, players: pd.DataFrame) -> pd.DataFrame:
    """Pull a manager's 15-man squad for a given GW from the FPL API."""
    payload = client.manager_picks(tid, gw)
    picks = pd.DataFrame(payload["picks"])
    # picks has: element, position (squad order 1-15), is_captain, is_vice_captain, multiplier
    picks = picks.rename(columns={"element": "player_id"})

    # Selling price isn't in the public picks endpoint — use current market price as a proxy.
    cols = ["player_id", "position", "team", "price", "web_name", "team_name"]
    cols = [c for c in cols if c in players.columns]
    squad = picks[["player_id"]].merge(players[cols], on="player_id", how="left")
    squad["selling_price"] = squad["price"]
    return squad


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tid", type=int, required=True, help="Your FPL team ID.")
    p.add_argument("--bank", type=float, default=0.0, help="Money in the bank (£m).")
    p.add_argument("--free", type=int, default=1, help="Free transfers available.")
    p.add_argument("--max-transfers", type=int, default=2)
    p.add_argument("--gw", type=int, default=None)
    p.add_argument("--model", default=str(DEFAULT_MODEL_PATH))
    args = p.parse_args()

    print("Loading data + model...")
    client = FPLClient()
    boot = client.bootstrap()
    target_gw = args.gw or next_gameweek(boot)
    snapshot_gw = current_gameweek(boot)

    data = load_or_fetch(client=client)
    players, history, fixtures = data["players"], data["history"], data["fixtures"]
    bundle = load_model(args.model)
    train = build_training_set(history, players)
    preds = predict_next_gw(bundle, train, players, fixtures, next_gw=target_gw)
    # The optimizer needs `team`; predict_next_gw already includes it.

    print(f"  fetching current squad for team {args.tid} (GW{snapshot_gw})...")
    squad = fetch_current_squad(client, args.tid, snapshot_gw, players)
    print(f"  squad players: {len(squad)}    bank: £{args.bank:.1f}m    free transfers: {args.free}")
    print()
    print("Current squad:")
    show = ["web_name", "team_name", "position", "price"]
    show = [c for c in show if c in squad.columns]
    print(squad[show].rename(columns={"web_name": "player", "team_name": "team"}).to_string(index=False))

    print(f"\nPlanning transfers for GW{target_gw}...")
    report = plan_transfers(
        current_squad=squad,
        predictions=preds,
        bank=args.bank,
        free_transfers=args.free,
        max_transfers=args.max_transfers,
    )

    print()
    print(format_report(report, preds, top_n=5))


if __name__ == "__main__":
    main()
