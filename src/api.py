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
from fastapi.middleware.cors import CORSMiddleware

from .data_loader import build_training_set, load_or_fetch
from .fpl_api import FPLClient, current_gameweek, next_gameweek
from .model import DEFAULT_MODEL_PATH, ModelBundle, load_model, predict_next_gw
from .optimizer import pick_team, select_squad, pick_starting_xi
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

# Allow the React dev server (and any locally-hosted frontend) to call us.
# Extra origins can be supplied via the FPL_AI_CORS_ORIGINS env var
# (comma-separated). Use "*" to allow any origin (handy for early prod testing).
import os as _os
_extra = [
    o.strip()
    for o in _os.environ.get("FPL_AI_CORS_ORIGINS", "").split(",")
    if o.strip()
]
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://localhost",
    "http://127.0.0.1",
]
_allow_origins = _extra if "*" in _extra else (_default_origins + _extra)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=".*" if "*" in _extra else None,
    allow_methods=["GET"],
    allow_headers=["*"],
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


@app.get("/live-scores")
def live_scores(gw: int | None = None) -> dict:
    """Fixtures + (live) scores. Defaults to the *next* gameweek so the UI shows
    upcoming fixtures rather than already-finished ones."""
    boot = state.client.bootstrap()
    target = int(gw) if gw is not None else (next_gameweek(boot) or current_gameweek(boot))

    teams = {
        t["id"]: {"name": t["name"], "short": t["short_name"], "code": t["code"]}
        for t in boot["teams"]
    }
    fxs = state.client.fixtures()  # always pull live so scores are current
    rows = []
    for f in fxs:
        if f.get("event") != target:
            continue
        h, a = f["team_h"], f["team_a"]
        ht, at = teams.get(h, {}), teams.get(a, {})
        rows.append({
            "id": f["id"],
            "kickoff_time": f.get("kickoff_time"),
            "started": bool(f.get("started")),
            "finished": bool(f.get("finished")),
            "minutes": f.get("minutes", 0),
            "home_team": ht.get("name", str(h)),
            "home_short": ht.get("short", str(h)),
            "home_code": ht.get("code"),
            "away_team": at.get("name", str(a)),
            "away_short": at.get("short", str(a)),
            "away_code": at.get("code"),
            "home_score": f.get("team_h_score"),
            "away_score": f.get("team_a_score"),
        })
    rows.sort(key=lambda r: (r["kickoff_time"] or ""))
    return {"gameweek": target, "fixtures": rows}


@app.get("/predictions")
def predictions(
    gw: int | None = Query(default=None, description="Target GW (defaults to next)."),
    top: int = Query(default=50, ge=1, le=830),
    q: str | None = Query(default=None, description="Case-insensitive substring filter on player or team name."),
) -> dict:
    """Ranked xPoints for the upcoming gameweek, with last GW's actual points."""
    target = _resolve_gw(gw)
    preds = _predictions_for(target).copy()

    # Attach last-GW actual points (realised) so users can sanity-check xP.
    boot = state.client.bootstrap()
    cur = current_gameweek(boot)
    last_gw = cur if cur and cur < target else (target - 1 if target > 1 else None)
    last_points: dict[int, int] = {}
    last_minutes: dict[int, int] = {}
    if last_gw and last_gw >= 1:
        try:
            live = state.client.event_live(last_gw)
            for el in live.get("elements", []):
                pid = int(el.get("id", 0))
                stats = el.get("stats", {}) or {}
                last_points[pid] = int(stats.get("total_points", 0))
                last_minutes[pid] = int(stats.get("minutes", 0))
        except Exception:
            last_gw = None

    preds["last_gw_points"] = preds["player_id"].map(last_points).fillna(0).astype(int)
    preds["last_gw_minutes"] = preds["player_id"].map(last_minutes).fillna(0).astype(int)

    # Optional name / team filter
    if q:
        needle = q.strip().lower()
        if needle:
            mask = (
                preds["web_name"].astype(str).str.lower().str.contains(needle, na=False)
                | preds["team_name"].astype(str).str.lower().str.contains(needle, na=False)
            )
            preds = preds[mask]

    preds = preds.head(top)
    return {
        "gameweek": target,
        "last_gameweek": last_gw,
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


def _formation_str(starting: pd.DataFrame) -> str:
    counts = starting["position"].value_counts().to_dict()
    return f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"


@app.get("/my-team")
def my_team(
    tid: int = Query(..., description="FPL team id."),
    gw: int | None = None,
) -> dict:
    """Return the manager's *actual* current squad enriched with xPoints
    for the next GW, plus their bank and an estimate of free transfers."""
    boot = state.client.bootstrap()
    snapshot_gw = current_gameweek(boot)
    target = _resolve_gw(gw)

    try:
        payload = state.client.manager_picks(tid, snapshot_gw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"Could not fetch team {tid}: {e}") from e

    picks = pd.DataFrame(payload["picks"]).rename(
        columns={"element": "player_id", "position": "squad_slot"}
    )
    eh = payload.get("entry_history", {}) or {}

    # Apply any transfers the manager has confirmed for an upcoming GW.
    # The picks endpoint only returns the squad as fielded in `snapshot_gw`;
    # transfers made *after* that GW's deadline (for GW snapshot_gw+1, etc.)
    # don't appear there until the next deadline passes. We patch them in so
    # the UI reflects the manager's *current* live squad.
    pending_transfers: list[dict] = []
    try:
        all_transfers = state.client.manager_transfers(tid)
        pending_transfers = [
            t for t in all_transfers if int(t.get("event", 0)) > snapshot_gw
        ]
    except Exception:  # noqa: BLE001 — non-fatal; fall back to last-GW squad.
        all_transfers = []

    if pending_transfers:
        # Apply oldest-first so chained swaps land on the right player.
        pending_transfers.sort(key=lambda t: (int(t["event"]), t.get("time", "")))
        slot_by_player = dict(zip(picks["player_id"], picks["squad_slot"]))
        for t in pending_transfers:
            out_id = int(t["element_out"])
            in_id = int(t["element_in"])
            if out_id in slot_by_player:
                slot = slot_by_player.pop(out_id)
                slot_by_player[in_id] = slot
        # Rebuild picks preserving slot/captain flags. Captain/vice flags are
        # invalid if the captained player was sold — clear them in that case.
        new_rows = []
        old_by_player = picks.set_index("player_id").to_dict("index")
        for player_id, slot in slot_by_player.items():
            old = old_by_player.get(player_id, {})
            new_rows.append({
                "player_id": player_id,
                "squad_slot": slot,
                "multiplier": old.get("multiplier", 1 if slot <= 11 else 0),
                "is_captain": bool(old.get("is_captain", False)) and player_id in old_by_player,
                "is_vice_captain": bool(old.get("is_vice_captain", False)) and player_id in old_by_player,
                "element_type": old.get("element_type"),
            })
        picks = pd.DataFrame(new_rows)

    # FPL stores money in tenths of a million.
    bank_m = float(eh.get("bank", 0)) / 10.0
    squad_value_m = float(eh.get("value", 0)) / 10.0
    last_transfers = int(eh.get("event_transfers", 0))
    event_points = int(eh.get("points", 0))
    total_points = int(eh.get("total_points", 0))
    # Public API doesn't expose `free_transfers` directly; estimate from last GW.
    # FPL rules (current): 1 free per GW, unused rolls over up to a max of 5.
    free_transfers_est = 2 if last_transfers == 0 else 1

    # Adjust bank/value/free transfers for any pending transfers we just applied.
    n_pending = len(pending_transfers)
    if n_pending:
        cash_delta = sum(
            (int(t.get("element_out_cost", 0)) - int(t.get("element_in_cost", 0)))
            for t in pending_transfers
        ) / 10.0
        bank_m = round(bank_m + cash_delta, 1)
        squad_value_m = round(squad_value_m - cash_delta, 1)
        free_transfers_est = max(0, free_transfers_est - n_pending)

    # Enrich picks with player metadata
    cols = [c for c in ("player_id", "web_name", "team_name", "team_code", "position", "team", "price")
            if c in state.players.columns]
    enriched = picks.merge(state.players[cols], on="player_id", how="left")

    # Attach xPoints for target GW
    preds = _predictions_for(target)[["player_id", "xPoints"]]
    enriched = enriched.merge(preds, on="player_id", how="left")
    enriched["xPoints"] = enriched["xPoints"].fillna(0.0)

    # Captain / vice from the picks payload
    captain_row = enriched[enriched["is_captain"] == True]  # noqa: E712
    vice_row = enriched[enriched["is_vice_captain"] == True]  # noqa: E712
    captain_id = int(captain_row["player_id"].iloc[0]) if len(captain_row) else 0
    vice_id = int(vice_row["player_id"].iloc[0]) if len(vice_row) else 0

    # `squad_slot` 1-11 = starting XI, 12-15 = bench (in subbing-on order)
    enriched = enriched.sort_values("squad_slot").reset_index(drop=True)
    starting_xi = enriched[enriched["squad_slot"] <= 11].copy()
    bench = enriched[enriched["squad_slot"] > 11].copy()

    # ---- Chip recommendations ---------------------------------------------
    # Each manager gets 2 of every chip per season (current FPL rules).
    chips_used: list[dict] = []
    try:
        chips_used = state.client.manager_history(tid).get("chips", []) or []
    except Exception:
        chips_used = []
    used_counts = {"wildcard": 0, "freehit": 0, "bboost": 0, "3xc": 0}
    for c in chips_used:
        nm = c.get("name")
        if nm in used_counts:
            used_counts[nm] += 1
    CHIP_LIMIT = 2
    remaining = {k: max(0, CHIP_LIMIT - v) for k, v in used_counts.items()}

    chip_recs: list[dict] = []
    xi_xp = float(starting_xi["xPoints"].sum())
    captain_xp_val = float(captain_row["xPoints"].iloc[0]) if len(captain_row) else 0.0
    bench_xp_val = float(bench["xPoints"].sum())
    base_xp = round(xi_xp + captain_xp_val, 2)  # XI + captain bonus (already 2x)

    # The current armband holder + alternate top scorer (for "switch the C" tip)
    cur_cap_name = (
        str(captain_row["web_name"].iloc[0]) if len(captain_row) else "—"
    )
    xi_ranked = starting_xi.sort_values("xPoints", ascending=False).reset_index(drop=True)
    best_cap_id = int(xi_ranked.iloc[0]["player_id"]) if len(xi_ranked) else 0
    best_cap_name = str(xi_ranked.iloc[0]["web_name"]) if len(xi_ranked) else "—"
    best_cap_xp = float(xi_ranked.iloc[0]["xPoints"]) if len(xi_ranked) else 0.0
    best_cap_team_id = int(xi_ranked.iloc[0]["team"]) if len(xi_ranked) else 0

    # team id -> badge code (for club logos in chip recs)
    team_code_map = {
        int(t["id"]): int(t["code"]) for t in state.client.bootstrap().get("teams", [])
    }
    best_cap_team_code = team_code_map.get(best_cap_team_id, 0)

    # Triple Captain: extra captain points on top of normal 2x.
    # Suggest the BEST scorer in the XI, not necessarily who they currently captain.
    if remaining["3xc"] > 0:
        switch = best_cap_id != captain_id
        # If switching armband + TC: total = XI + 2x best_cap (replaces 1x captain bonus).
        # If keeping armband + TC:   total = XI + 2x current captain (one extra cap multiplier).
        total_with_chip = (
            round(xi_xp + 2 * best_cap_xp, 2)
            if switch
            else round(base_xp + captain_xp_val, 2)
        )
        delta_tc = round(total_with_chip - base_xp, 2)
        chip_recs.append({
            "chip": "3xc",
            "label": "Triple Captain",
            "xpoints_with_chip": total_with_chip,
            "delta": delta_tc,
            "recommend": best_cap_xp >= 7.0,
            "captain_name": best_cap_name,
            "captain_id": best_cap_id,
            "captain_xpoints": round(best_cap_xp, 2),
            "captain_team_code": best_cap_team_code,
            "note": (
                f"Switch armband to {best_cap_name} and triple — projected {best_cap_xp:.1f} xP × 3 "
                f"(currently captaining {cur_cap_name})."
                if switch
                else f"Triple {best_cap_name} — already your captain, projected {best_cap_xp:.1f} xP × 3."
            ),
        })

    # Bench Boost: bench points count this week.
    if remaining["bboost"] > 0:
        bench_sorted = bench.sort_values("xPoints", ascending=False)
        bench_players = [
            {
                "player_id": int(r.player_id),
                "name": str(r.web_name),
                "position": str(r.position),
                "team_name": str(r.team_name),
                "team_code": team_code_map.get(int(r.team), 0),
                "xpoints": round(float(r.xPoints), 2),
            }
            for r in bench_sorted.itertuples()
        ]
        chip_recs.append({
            "chip": "bboost",
            "label": "Bench Boost",
            "xpoints_with_chip": round(base_xp + bench_xp_val, 2),
            "delta": round(bench_xp_val, 2),
            "recommend": bench_xp_val >= 12.0,
            "bench_players": bench_players,
            "note": f"Adds {bench_xp_val:.1f} xP from your bench this week.",
        })
    # Wildcard / Free Hit: build optimal squad from full pool within current budget.
    # - Free Hit optimises for ONE GW (target).
    # - Wildcard optimises for the average over the next WC_HORIZON GWs.
    WC_HORIZON = 5
    budget_total = round(bank_m + squad_value_m, 1)
    ideal_squads: dict[str, dict | None] = {"wildcard": None, "freehit": None}

    def _build_ideal(preds_df: pd.DataFrame) -> dict | None:
        try:
            opt_squad = select_squad(preds_df, budget=budget_total)
            opt_xi, opt_bench_df, opt_form = pick_starting_xi(opt_squad)
            opt_xi_sorted = opt_xi.sort_values("xPoints", ascending=False).reset_index(drop=True)
            cap_id = int(opt_xi_sorted.iloc[0]["player_id"]) if len(opt_xi_sorted) else 0
            vc_id = int(opt_xi_sorted.iloc[1]["player_id"]) if len(opt_xi_sorted) > 1 else 0
            cap_xp = float(opt_xi_sorted.iloc[0]["xPoints"]) if len(opt_xi_sorted) else 0.0
            xi_xp_total = float(opt_xi["xPoints"].sum())
            # Tag rows so the frontend Pitch component can render them
            opt_xi = opt_xi.assign(
                squad_slot=range(1, len(opt_xi) + 1),
                multiplier=lambda d: [2 if pid == cap_id else 1 for pid in d["player_id"]],
                is_captain=lambda d: d["player_id"] == cap_id,
                is_vice_captain=lambda d: d["player_id"] == vc_id,
            )
            opt_bench_df = opt_bench_df.assign(
                squad_slot=range(12, 12 + len(opt_bench_df)),
                multiplier=0,
                is_captain=False,
                is_vice_captain=False,
            )
            return {
                "formation": opt_form,
                "captain_id": cap_id,
                "vice_captain_id": vc_id,
                "total_xpoints": round(xi_xp_total + cap_xp, 2),
                "total_cost": round(float(opt_squad["price"].sum()), 1),
                "starting_xi": _df_to_json(opt_xi),
                "bench": _df_to_json(opt_bench_df),
            }
        except Exception:
            return None

    if remaining["freehit"] > 0:
        try:
            preds_fh = _predictions_for(target)
            sq = _build_ideal(preds_fh)
            if sq is not None:
                sq["delta_vs_current"] = round(sq["total_xpoints"] - base_xp, 2)
                sq["horizon"] = 1
                sq["gameweek"] = target
                ideal_squads["freehit"] = sq
        except Exception:
            pass

    if remaining["wildcard"] > 0:
        try:
            # Average xPoints across the next WC_HORIZON GWs (clipped to GW38)
            horizon_gws = [g for g in range(target, min(target + WC_HORIZON, 39))]
            frames = []
            for g in horizon_gws:
                try:
                    df_g = _predictions_for(g)
                    keep = [c for c in ("player_id", "web_name", "team_name", "team_code",
                                        "position", "team", "price", "xPoints") if c in df_g.columns]
                    frames.append(df_g[keep])
                except Exception:
                    continue
            if frames:
                stacked = pd.concat(frames, ignore_index=True)
                preds_wc = (
                    stacked.groupby(
                        [c for c in ("player_id", "web_name", "team_name", "team_code",
                                     "position", "team", "price") if c in stacked.columns],
                        as_index=False,
                    )["xPoints"].mean()
                )
                sq = _build_ideal(preds_wc)
                if sq is not None:
                    sq["delta_vs_current"] = round(sq["total_xpoints"] - base_xp, 2)
                    sq["horizon"] = len(horizon_gws)
                    sq["gameweek"] = target
                    sq["horizon_end"] = horizon_gws[-1]
                    ideal_squads["wildcard"] = sq
        except Exception:
            pass

    chip_recs.sort(key=lambda c: c["delta"], reverse=True)

    return {
        "team_id": tid,
        "snapshot_gameweek": snapshot_gw,
        "target_gameweek": target,
        "bank": bank_m,
        "squad_value": squad_value_m,
        "total_budget": round(bank_m + squad_value_m, 1),
        "free_transfers_estimate": free_transfers_est,
        "last_event_transfers": last_transfers,
        "event_points": event_points,
        "total_points": total_points,
        "formation": _formation_str(starting_xi),
        "captain_id": captain_id,
        "vice_captain_id": vice_id,
        "total_xpoints": round(float(starting_xi["xPoints"].sum()), 2),
        "starting_xi": _df_to_json(starting_xi),
        "bench": _df_to_json(bench),
        "chips_remaining": remaining,
        "chips_used": chips_used,
        "chip_recommendations": chip_recs,
        "ideal_squads": ideal_squads,
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
