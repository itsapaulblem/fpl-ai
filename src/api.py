"""Phase 8 — FastAPI service.

Exposes the model + optimizer + transfer planner over HTTP so the UI
(Phase 11) and any other client can consume them as JSON.

Routes:
    GET  /health                       liveness check
    GET  /gameweek                     current + next GW from the FPL API
    GET  /predictions?gw=&top=         ranked xPoints for a given GW
    GET  /squad?budget=&gw=            optimal 15-man squad + XI + captain
    GET  /transfers?tid=&bank=&free=   transfer recommendations for a real team

Heavy state (the model bundle, cached data, training set) is loaded ONCE on
startup via FastAPI's `lifespan` hook and reused across requests — so each
HTTP call is just a model.predict() + a tiny ILP, not a full data refresh.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query

from .data_loader import build_training_set, load_or_fetch
from .fpl_api import FPLClient, current_gameweek, next_gameweek
from .model import DEFAULT_MODEL_PATH, ModelBundle, load_model, predict_next_gw
from .optimizer import pick_team
from .transfer_planner import plan_transfers


# ---------------------------------------------------------------------- #
# Shared state, populated on startup
# ---------------------------------------------------------------------- #
class AppState:
    client: FPLClient
    bundle: ModelBundle
    players: pd.DataFrame
    history: pd.DataFrame
    fixtures: pd.DataFrame
    training: pd.DataFrame


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load model + cached data once when the server boots."""
    state.client = FPLClient()
    state.bundle = load_model(DEFAULT_MODEL_PATH)

    data = load_or_fetch(client=state.client)
    state.players = data["players"]
    state.history = data["history"]
    state.fixtures = data["fixtures"]
    state.training = build_training_set(state.history, state.players)
    yield
    # nothing to tear down


app = FastAPI(
    title="FPL AI",
    description="Fantasy Premier League squad recommender + transfer planner.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _resolve_gw(gw: int | None) -> int:
    if gw is not None:
        return int(gw)
    return next_gameweek(state.client.bootstrap())


def _df_to_json(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-friendly dict-list with NaN -> None."""
    return df.where(pd.notna(df), None).to_dict(orient="records")


def _predictions_for(gw: int) -> pd.DataFrame:
    preds = predict_next_gw(
        state.bundle, state.training, state.players, state.fixtures, next_gw=gw
    )
    if preds.empty:
        raise HTTPException(404, f"No predictions available for GW{gw}.")
    return preds


# ---------------------------------------------------------------------- #
# Routes
# ---------------------------------------------------------------------- #
@app.get("/")
def root() -> dict:
    """Landing page — lists the available endpoints."""
    return {
        "service": "fpl-ai",
        "docs": "/docs",
        "endpoints": [
            "/health",
            "/gameweek",
            "/predictions?gw=&top=",
            "/squad?gw=&budget=",
            "/transfers?tid=&bank=&free=&max_transfers=",
        ],
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_trained_through_gw": state.bundle.trained_through_gw,
        "model_val_rmse": state.bundle.metrics["rmse"],
        "n_players": int(len(state.players)),
    }


@app.get("/gameweek")
def gameweek() -> dict:
    boot = state.client.bootstrap()
    return {
        "current": current_gameweek(boot),
        "next": next_gameweek(boot),
    }


@app.get("/predictions")
def predictions(
    gw: int | None = Query(default=None, description="Target GW (defaults to next)."),
    top: int = Query(default=50, ge=1, le=830),
) -> dict:
    """Ranked xPoints for the upcoming gameweek."""
    target = _resolve_gw(gw)
    preds = _predictions_for(target).head(top)
    return {
        "gameweek": target,
        "count": len(preds),
        "players": _df_to_json(preds),
    }


@app.get("/squad")
def squad(
    gw: int | None = None,
    budget: float = Query(default=100.0, ge=50.0, le=200.0),
) -> dict:
    """Recommend the optimal 15-man squad + XI + captain for a GW."""
    target = _resolve_gw(gw)
    preds = _predictions_for(target)
    try:
        sel = pick_team(preds, budget=budget)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    return {
        "gameweek": target,
        "formation": sel.formation,
        "total_cost": round(sel.total_cost, 2),
        "total_xpoints": round(sel.total_xpoints, 2),
        "captain_id": sel.captain_id,
        "vice_captain_id": sel.vice_captain_id,
        "starting_xi": _df_to_json(sel.starting_xi),
        "bench": _df_to_json(sel.bench),
    }


@app.get("/transfers")
def transfers(
    tid: int = Query(..., description="FPL team id."),
    bank: float = Query(default=0.0, ge=0.0, le=20.0),
    free: int = Query(default=1, ge=0, le=5),
    max_transfers: int = Query(default=2, ge=0, le=2),
    gw: int | None = None,
    top: int = Query(default=5, ge=1, le=20),
) -> dict:
    """Transfer recommendations for an existing FPL team."""
    boot = state.client.bootstrap()
    target = _resolve_gw(gw)
    snapshot_gw = current_gameweek(boot)

    try:
        payload = state.client.manager_picks(tid, snapshot_gw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"Could not fetch team {tid}: {e}") from e

    picks = pd.DataFrame(payload["picks"]).rename(columns={"element": "player_id"})
    cols = [c for c in ("player_id", "position", "team", "price", "web_name", "team_name")
            if c in state.players.columns]
    current = picks[["player_id"]].merge(state.players[cols], on="player_id", how="left")
    current["selling_price"] = current["price"]

    preds = _predictions_for(target)
    report = plan_transfers(
        current_squad=current,
        predictions=preds,
        bank=bank,
        free_transfers=free,
        max_transfers=max_transfers,
    )

    name_map = {int(r.player_id): r.web_name for r in preds.itertuples()
                if hasattr(r, "web_name")}

    def serialize(plan):
        return {
            "transfers_out": [
                {"player_id": pid, "name": name_map.get(pid, str(pid))}
                for pid in plan.transfers_out
            ],
            "transfers_in": [
                {"player_id": pid, "name": name_map.get(pid, str(pid))}
                for pid in plan.transfers_in
            ],
            "n_transfers": plan.n_transfers,
            "hit_cost": plan.hit_cost,
            "xi_xpoints": round(plan.xi_xpoints, 2),
            "net_xpoints": round(plan.net_xpoints, 2),
            "bank_after": round(plan.bank_after, 2),
            "formation": plan.formation,
            "captain_id": plan.captain_id,
            "captain_name": name_map.get(plan.captain_id, str(plan.captain_id)),
        }

    best = report.best()
    return {
        "team_id": tid,
        "snapshot_gameweek": snapshot_gw,
        "target_gameweek": target,
        "bank": bank,
        "free_transfers": free,
        "baseline": serialize(report.baseline),
        "best": serialize(best),
        "best_is_no_transfer": best is report.baseline,
        "alternatives": [serialize(p) for p in report.plans[:top]],
    }
