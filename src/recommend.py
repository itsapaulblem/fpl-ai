"""End-to-end pipeline: fetch -> train -> predict -> optimise."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .data_loader import (
    PROC_DIR, build_training_set, fetch_bootstrap, fetch_fixtures,
    fetch_player_histories, players_frame, save_parquet, upcoming_fixtures,
)
from .fpl_api import FPLClient, next_gameweek
from .model import predict_next_gw, save, train
from .optimizer import pick_squad, recommend_transfers


def run_pipeline(
    horizon: int = 1,
    budget: float = 100.0,
    current_team_id: int | None = None,
    save_artifacts: bool = True,
) -> dict:
    """Fetch fresh data, retrain, and emit a recommendation.

    Returns a dict with squad, starting_xi, transfers (optional), metrics.
    """
    client = FPLClient()
    print("[1/5] Fetching bootstrap & fixtures...")
    boot = fetch_bootstrap(client)
    players = players_frame(boot)
    fixtures = fetch_fixtures(client)
    nxt = next_gameweek(boot)
    print(f"      Next GW: {nxt} | players: {len(players)} | teams: {players['team'].nunique()}")

    print("[2/5] Fetching player histories (this is the slow step)...")
    history = fetch_player_histories(boot, client)
    if save_artifacts:
        save_parquet(players, PROC_DIR / "players.parquet")
        save_parquet(history, PROC_DIR / "history.parquet")
        save_parquet(fixtures, PROC_DIR / "fixtures.parquet")

    print("[3/5] Building training set & training model...")
    train_df = build_training_set(history, players, fixtures)
    if train_df.empty or len(train_df) < 200:
        print("      WARNING: Very little history available (early season). "
              "Falling back to FPL form as xPoints proxy.")
        players["xPoints"] = (
            pd.to_numeric(players.get("form", 0), errors="coerce").fillna(0)
            * max(horizon, 1)
        )
        result = None
    else:
        result = train(train_df)
        print(f"      Validation MAE={result.mae:.3f}  RMSE={result.rmse:.3f}")
        if save_artifacts:
            save(result)

    print("[4/5] Predicting xPoints for upcoming gameweek(s)...")
    if result is not None:
        upc = upcoming_fixtures(fixtures, players, nxt, horizon=horizon)
        players_x = predict_next_gw(
            result.model, result.features, players, history, upc
        )
    else:
        players_x = players.copy()

    # Filter unavailable players (injured / suspended)
    avail = players_x.copy()
    if "status" in avail.columns:
        avail = avail[avail["status"].isin(["a", "d"])]  # available / doubt
    if "chance_of_playing_next_round" in avail.columns:
        cop = pd.to_numeric(avail["chance_of_playing_next_round"], errors="coerce")
        avail = avail[(cop.isna()) | (cop >= 50)]

    print("[5/5] Optimising squad...")
    squad_res = pick_squad(avail, budget=budget)

    out = {
        "next_gw": nxt,
        "horizon": horizon,
        "squad": squad_res.squad,
        "starting_xi": squad_res.starting_xi,
        "expected_points_with_captain": squad_res.expected_points,
        "total_cost": squad_res.total_cost,
        "metrics": None if result is None else {"mae": result.mae, "rmse": result.rmse},
    }

    if current_team_id is not None:
        try:
            picks = client.manager_picks(current_team_id, max(nxt - 1, 1))
            cur_ids = [p["element"] for p in picks["picks"]]
            out["transfers"] = recommend_transfers(cur_ids, avail, budget=budget)
        except Exception as e:
            out["transfers_error"] = str(e)

    return out


def format_report(result: dict) -> str:
    lines: list[str] = []
    lines.append(f"=== FPL AI Recommendation — GW{result['next_gw']} "
                 f"(horizon={result['horizon']}) ===")
    if result.get("metrics"):
        m = result["metrics"]
        lines.append(f"Model validation: MAE={m['mae']:.3f}  RMSE={m['rmse']:.3f}")
    lines.append(f"Total squad cost: £{result['total_cost']:.1f}m / budget")
    lines.append(f"Expected points (XI + captain bonus): {result['expected_points_with_captain']:.2f}")
    lines.append("")
    lines.append("--- Starting XI ---")
    xi = result["starting_xi"][[
        "position", "web_name", "team_name", "price", "xPoints",
        "is_captain", "is_vice",
    ]]
    lines.append(xi.to_string(index=False))
    lines.append("")
    lines.append("--- Bench ---")
    bench_ids = set(result["squad"]["player_id"]) - set(result["starting_xi"]["player_id"])
    bench = result["squad"][result["squad"]["player_id"].isin(bench_ids)][
        ["position", "web_name", "team_name", "price", "xPoints"]
    ]
    lines.append(bench.to_string(index=False))

    if "transfers" in result and not result["transfers"].empty:
        lines.append("")
        lines.append("--- Top Transfer Suggestions ---")
        lines.append(result["transfers"].head(5).to_string(index=False))
    return "\n".join(lines)
