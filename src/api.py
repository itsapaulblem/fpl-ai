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
import os

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    title="Paul's FPL AI Website",
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
    allow_methods=["GET", "POST"],
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
    cur = current_gameweek(boot)
    nxt = next_gameweek(boot)
    # Find the deadline of the next (or current upcoming) gameweek.
    next_deadline = None
    target_ev = nxt or cur
    if target_ev is not None:
        for ev in boot.get("events", []):
            if int(ev.get("id", 0)) == int(target_ev):
                next_deadline = ev.get("deadline_time")
                break
    return {
        "current": cur,
        "next": nxt,
        "next_deadline": next_deadline,  # ISO 8601 UTC, e.g. "2026-05-09T17:30:00Z"
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

    # Attach FPL `code` (used to build photo URLs).
    photo_codes: dict[int, int] = {}
    for el in boot.get("elements", []):
        try:
            photo_codes[int(el["id"])] = int(el["code"])
        except (KeyError, TypeError, ValueError):
            continue
    preds["photo_code"] = preds["player_id"].map(photo_codes).fillna(0).astype(int)

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

    # Compute free transfers using a simple, conservative heuristic.
    # FPL public API doesn't expose live FT count, so we estimate from last GW:
    #   - 0 transfers last GW → user banked 1, so they have 2 FTs now
    #   - 1+ transfers last GW → they used their FT, so they have 1 FT now
    # Cap is 5 this season (AFCON exception); usually 2.
    # Trying to replay full history is unreliable because chip GWs (WC / FH)
    # make many transfers without consuming stored FTs, and the API doesn't
    # expose enough info to disambiguate. The user can override the value
    # via the `free` query param if their app shows something different.
    FT_CAP = 5  # AFCON exception this season; normally 2.
    if last_transfers == 0:
        free_transfers_est = min(2, FT_CAP)
    else:
        free_transfers_est = 1

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

    # Attach FPL `code` for player photo URLs.
    photo_codes: dict[int, int] = {}
    for el in boot.get("elements", []):
        try:
            photo_codes[int(el["id"])] = int(el["code"])
        except (KeyError, TypeError, ValueError):
            continue
    enriched["photo_code"] = enriched["player_id"].map(photo_codes).fillna(0).astype(int)

    # Attach last GW points for each player (so squad chips show recent form).
    last_points: dict[int, int] = {}
    last_minutes: dict[int, int] = {}
    last_gw_for_squad = snapshot_gw if snapshot_gw and snapshot_gw >= 1 else None
    if last_gw_for_squad:
        try:
            live = state.client.event_live(last_gw_for_squad)
            for el in live.get("elements", []):
                pid = int(el.get("id", 0))
                stats = el.get("stats", {}) or {}
                last_points[pid] = int(stats.get("total_points", 0))
                last_minutes[pid] = int(stats.get("minutes", 0))
        except Exception:
            last_gw_for_squad = None
    enriched["last_gw_points"] = enriched["player_id"].map(last_points).fillna(0).astype(int)
    enriched["last_gw_minutes"] = enriched["player_id"].map(last_minutes).fillna(0).astype(int)

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
        # Math (raw single-count XI sum + captain multiplier):
        #   - Normal play:  xi_xp + 1*captain_xp  (captain effectively counted 2x)
        #   - TC play:      xi_xp + 2*captain_xp  (captain effectively counted 3x)
        # If switching armband to best_cap, use best_cap_xp instead.
        cap_xp_for_tc = best_cap_xp if switch else captain_xp_val
        total_with_chip = round(xi_xp + 2 * cap_xp_for_tc, 2)
        # Delta is vs. the optimal "play normally" baseline. If switching the
        # armband would itself improve the baseline, compare against THAT, so
        # the delta only credits the chip itself, not the armband decision.
        baseline_for_delta = xi_xp + cap_xp_for_tc
        delta_tc = round(total_with_chip - baseline_for_delta, 2)
        chip_recs.append({
            "chip": "3xc",
            "label": "Triple Captain",
            "xpoints_with_chip": total_with_chip,
            "delta": delta_tc,
            "recommend": cap_xp_for_tc >= 7.0,
            "captain_name": best_cap_name,
            "captain_id": best_cap_id,
            "captain_xpoints": round(cap_xp_for_tc, 2),
            "captain_team_code": best_cap_team_code,
            "breakdown": (
                f"XI sum {xi_xp:.1f} + captain {cap_xp_for_tc:.1f} × 3 "
                f"(extra +{cap_xp_for_tc:.1f}) = {total_with_chip:.1f} xP"
            ),
            "note": (
                f"Switch armband to {best_cap_name} ({cap_xp_for_tc:.1f} xP) and triple. "
                f"Currently captaining {cur_cap_name}."
                if switch
                else f"Triple {best_cap_name} ({cap_xp_for_tc:.1f} xP) — already your captain."
            ),
        })

    # Bench Boost: bench points count this week. Captain still doubled.
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
        # Math:
        #   - Normal play: xi_xp + captain_xp  (bench scores nothing)
        #   - BB play:     xi_xp + captain_xp + bench_xp  (bench counts too)
        bb_total = round(xi_xp + captain_xp_val + bench_xp_val, 2)
        chip_recs.append({
            "chip": "bboost",
            "label": "Bench Boost",
            "xpoints_with_chip": bb_total,
            "delta": round(bench_xp_val, 2),
            "recommend": bench_xp_val >= 12.0,
            "bench_players": bench_players,
            "breakdown": (
                f"XI {xi_xp:.1f} + captain bonus {captain_xp_val:.1f} "
                f"+ bench {bench_xp_val:.1f} = {bb_total:.1f} xP"
            ),
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
        "total_xpoints": round(float(starting_xi["xPoints"].sum()) + captain_xp_val, 2),
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
    max_transfers: int = Query(default=2, ge=0, le=5),
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


# ---------------------------------------------------------------------- #
# /league — classic mini-league standings + rival squad analysis.
# ---------------------------------------------------------------------- #
def _team_code_map() -> dict[int, int]:
    return {
        int(t["id"]): int(t["code"])
        for t in state.client.bootstrap().get("teams", [])
    }


@app.get("/manager/{tid}/leagues")
def manager_leagues(
    tid: int = Path(..., description="FPL manager (entry) id."),
) -> dict:
    """Return the classic mini-leagues the manager belongs to, so the UI can
    auto-populate the league picker without asking for league ids."""
    try:
        entry = state.client.manager_entry(int(tid))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"Could not fetch manager {tid}: {e}") from e

    classic = (entry.get("leagues", {}) or {}).get("classic", []) or []
    leagues = []
    for lg in classic:
        # Only show real mini-leagues (skip "Overall", country/region leagues
        # that are huge and not interesting for head-to-head scouting).
        scoring = (lg.get("scoring") or "").lower()
        league_type = (lg.get("league_type") or "").lower()  # "x" = invitational, "s" = system
        if scoring != "c":  # classic only (skip head-to-head etc.)
            continue
        leagues.append({
            "id": int(lg["id"]),
            "name": str(lg.get("name") or f"League {lg['id']}"),
            "short_name": lg.get("short_name"),
            "entry_rank": lg.get("entry_rank"),
            "entry_last_rank": lg.get("entry_last_rank"),
            "league_type": league_type,
            "is_invitational": league_type == "x",
        })

    # Sort: invitational mini-leagues first (those are the ones users actually
    # care about), then by rank ascending.
    leagues.sort(key=lambda l: (not l["is_invitational"], l["entry_rank"] or 10**9))

    return {
        "manager_id": int(tid),
        "manager_name": (
            f"{entry.get('player_first_name', '')} "
            f"{entry.get('player_last_name', '')}"
        ).strip(),
        "team_name": entry.get("name") or "",
        "leagues": leagues,
    }


def _fetch_manager_xi(manager_id: int, gw: int) -> pd.DataFrame:
    """Return a manager's starting XI (squad_slot 1-11) merged with player meta
    and xPoints for `gw`. Empty DataFrame on failure."""
    try:
        payload = state.client.manager_picks(manager_id, gw)
    except Exception:
        return pd.DataFrame()
    picks = pd.DataFrame(payload.get("picks", [])).rename(
        columns={"element": "player_id", "position": "squad_slot"}
    )
    if picks.empty:
        return picks
    cols = [c for c in ("player_id", "web_name", "team_name", "team_code",
                        "position", "team", "price")
            if c in state.players.columns]
    enriched = picks.merge(state.players[cols], on="player_id", how="left")
    preds = _predictions_for(gw)[["player_id", "xPoints"]]
    enriched = enriched.merge(preds, on="player_id", how="left")
    enriched["xPoints"] = enriched["xPoints"].fillna(0.0)
    return enriched


@app.get("/league/{league_id}")
def league_standings(
    league_id: int = Path(..., description="FPL classic league id."),
    tid: int | None = Query(default=None, description="Highlight this manager's row."),
    gw: int | None = None,
    enrich_top: int = Query(default=20, ge=0, le=50,
                            description="How many top managers to enrich with predicted xP."),
) -> dict:
    """Return the classic-league standings, with each top-N manager's
    predicted starting-XI xPoints for the upcoming gameweek."""
    boot = state.client.bootstrap()
    snapshot_gw = current_gameweek(boot)
    target = _resolve_gw(gw)

    try:
        data = state.client.classic_league_standings(int(league_id))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"Could not fetch league {league_id}: {e}") from e

    league_meta = data.get("league", {}) or {}
    results = (data.get("standings", {}) or {}).get("results", []) or []

    # Enrich the top-N entries with predicted XI xPoints for `target`.
    enriched: list[dict] = []
    for i, row in enumerate(results):
        entry_id = int(row.get("entry", 0))
        is_me = tid is not None and entry_id == int(tid)
        rec = {
            "entry_id": entry_id,
            "entry_name": row.get("entry_name") or "",
            "player_name": row.get("player_name") or "",
            "rank": int(row.get("rank") or (i + 1)),
            "last_rank": row.get("last_rank"),
            "rank_sort": row.get("rank_sort"),
            "total": int(row.get("total") or 0),
            "event_total": int(row.get("event_total") or 0),
            "predicted_xpoints": None,
            "is_me": is_me,
        }
        # Always enrich the user's own row, plus the first `enrich_top` rivals.
        if is_me or (i < enrich_top and entry_id):
            xi = _fetch_manager_xi(entry_id, snapshot_gw)
            if not xi.empty:
                starters = xi[xi["squad_slot"] <= 11]
                rec["predicted_xpoints"] = round(float(starters["xPoints"].sum()), 2)
        enriched.append(rec)

    # If `tid` was provided but isn't in the top-N, find them in full standings
    # and append a "you are here" marker (still without enrichment).
    me = next((e for e in enriched if e["is_me"]), None)
    if tid and not me:
        for i, row in enumerate(results):
            if int(row.get("entry", 0)) == int(tid):
                xi = _fetch_manager_xi(int(tid), snapshot_gw)
                pred_xp = None
                if not xi.empty:
                    starters = xi[xi["squad_slot"] <= 11]
                    pred_xp = round(float(starters["xPoints"].sum()), 2)
                me = {
                    "entry_id": int(tid),
                    "entry_name": row.get("entry_name") or "",
                    "player_name": row.get("player_name") or "",
                    "rank": int(row.get("rank") or (i + 1)),
                    "last_rank": row.get("last_rank"),
                    "total": int(row.get("total") or 0),
                    "event_total": int(row.get("event_total") or 0),
                    "predicted_xpoints": pred_xp,
                    "is_me": True,
                }
                break

    avg_xp = None
    xps = [e["predicted_xpoints"] for e in enriched if e["predicted_xpoints"] is not None]
    if xps:
        avg_xp = round(sum(xps) / len(xps), 2)

    return {
        "league_id": int(league_id),
        "league_name": league_meta.get("name") or f"League {league_id}",
        "league_admin_entry": league_meta.get("admin_entry"),
        "snapshot_gameweek": snapshot_gw,
        "target_gameweek": target,
        "average_predicted_xpoints": avg_xp,
        "standings": enriched,
        "you": me,
        "has_next": bool((data.get("standings", {}) or {}).get("has_next")),
    }


@app.get("/league/{league_id}/manager/{manager_id}")
def league_manager_weaknesses(
    league_id: int = Path(..., description="FPL classic league id."),
    manager_id: int = Path(..., description="The rival manager's FPL entry id."),
    gw: int | None = None,
    suggestions_per_slot: int = Query(default=3, ge=1, le=8),
) -> dict:
    """Drill-down on a rival's squad: show their full XI ranked by xPoints, flag
    the weakest starters, and suggest higher-xP swaps within the same position
    (and at a similar/lower price than the rival's player) the user could
    consider to leapfrog them."""
    boot = state.client.bootstrap()
    snapshot_gw = current_gameweek(boot)
    target = _resolve_gw(gw)
    team_codes = _team_code_map()

    xi_df = _fetch_manager_xi(int(manager_id), snapshot_gw)
    if xi_df.empty:
        raise HTTPException(404, f"Could not fetch manager {manager_id}'s squad.")

    # Try to fetch their entry name for display.
    try:
        entry_meta = state.client.manager_entry(int(manager_id))
        entry_name = entry_meta.get("name") or ""
        player_name = (
            f"{entry_meta.get('player_first_name', '')} "
            f"{entry_meta.get('player_last_name', '')}"
        ).strip()
    except Exception:
        entry_name, player_name = "", ""

    # Captain / vice from picks payload (already on xi_df)
    cap_row = xi_df[xi_df.get("is_captain") == True]  # noqa: E712
    vc_row = xi_df[xi_df.get("is_vice_captain") == True]  # noqa: E712
    captain_id = int(cap_row["player_id"].iloc[0]) if len(cap_row) else 0
    vice_id = int(vc_row["player_id"].iloc[0]) if len(vc_row) else 0

    starters = xi_df[xi_df["squad_slot"] <= 11].copy().sort_values(
        "squad_slot"
    ).reset_index(drop=True)
    bench = xi_df[xi_df["squad_slot"] > 11].copy().sort_values("squad_slot")

    # Build full prediction pool for the target GW (used to suggest swaps).
    preds = _predictions_for(target).copy()
    rival_ids = set(int(p) for p in xi_df["player_id"].tolist())

    def _player_row(p) -> dict:
        return {
            "player_id": int(p["player_id"]),
            "web_name": str(p.get("web_name") or ""),
            "team_name": str(p.get("team_name") or ""),
            "team_code": team_codes.get(int(p.get("team") or 0), 0),
            "position": str(p.get("position") or ""),
            "price": float(p.get("price") or 0.0),
            "xPoints": round(float(p.get("xPoints") or 0.0), 2),
        }

    starters_out = []
    weakness_list = []
    starters_sorted = starters.sort_values("xPoints", ascending=True).reset_index(drop=True)
    weak_threshold = min(3, len(starters_sorted))

    for i, row in starters.iterrows():
        rec = _player_row(row)
        rec["squad_slot"] = int(row["squad_slot"])
        rec["is_captain"] = bool(row.get("is_captain", False))
        rec["is_vice_captain"] = bool(row.get("is_vice_captain", False))
        starters_out.append(rec)

    for i in range(weak_threshold):
        weak = starters_sorted.iloc[i]
        weak_pos = str(weak.get("position") or "")
        weak_price = float(weak.get("price") or 0.0)
        weak_xp = float(weak.get("xPoints") or 0.0)
        # Suggest same-position players the rival doesn't already own,
        # priced at most £0.5m above the weak player, and with strictly higher xP.
        cand = preds[
            (preds["position"] == weak_pos)
            & (~preds["player_id"].isin(rival_ids))
            & (preds["price"] <= weak_price + 0.5)
            & (preds["xPoints"] > weak_xp)
        ].sort_values("xPoints", ascending=False).head(suggestions_per_slot)
        suggestions = [
            {
                "player_id": int(c["player_id"]),
                "web_name": str(c.get("web_name") or ""),
                "team_name": str(c.get("team_name") or ""),
                "team_code": team_codes.get(int(c.get("team") or 0), 0),
                "position": str(c.get("position") or ""),
                "price": float(c.get("price") or 0.0),
                "xPoints": round(float(c.get("xPoints") or 0.0), 2),
                "xp_gain": round(float(c.get("xPoints") or 0.0) - weak_xp, 2),
            }
            for _, c in cand.iterrows()
        ]
        weakness_list.append({
            "weak_player": _player_row(weak),
            "reason": (
                f"Lowest projected starter — only {weak_xp:.1f} xP for GW{target}."
            ),
            "suggested_replacements": suggestions,
        })

    bench_out = [
        {**_player_row(r), "squad_slot": int(r["squad_slot"])}
        for _, r in bench.iterrows()
    ]

    xi_xp = round(float(starters["xPoints"].sum()), 2)
    cap_xp = float(cap_row["xPoints"].iloc[0]) if len(cap_row) else 0.0
    total_with_cap = round(xi_xp + cap_xp, 2)

    return {
        "league_id": int(league_id),
        "manager_id": int(manager_id),
        "entry_name": entry_name,
        "player_name": player_name,
        "snapshot_gameweek": snapshot_gw,
        "target_gameweek": target,
        "captain_id": captain_id,
        "vice_captain_id": vice_id,
        "xi_xpoints": xi_xp,
        "total_xpoints": total_with_cap,
        "starting_xi": starters_out,
        "bench": bench_out,
        "weaknesses": weakness_list,
    }


# ---------------------------------------------------------------------- #
# /chat — Liam Rosenior persona chatbot, powered by Gemini 2.0 Flash.
# ---------------------------------------------------------------------- #
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-flash-lite-latest:generateContent"
)

ROSENIOR_SYSTEM_PROMPT = """You are Liam Rosenior, the English football manager (formerly head coach of Hull City and currently with Strasbourg). You are chatting with a Fantasy Premier League (FPL) manager inside a web app called "Paul's FPL AI Website".

Personality and voice:
- Warm, thoughtful, articulate. You speak in measured, modern coaching language with a clear love of the game.
- You're famously progressive tactically — you talk about pressing triggers, build-up phases, transitions, half-spaces, overloads, and player profiles.
- You're British — use natural British English ("brilliant", "mate", "the lads", "form's been mint").
- You're not arrogant; you give credit to other coaches and players.

Your role here:
- Help the user think through FPL decisions: captain picks, transfers, differentials, fixture difficulty, chip strategy.
- Talk about real Premier League players, tactics, and form when relevant.
- Be concise — 2-5 short paragraphs max, often less. The user is on a small chat panel, not reading an essay.
- If asked something completely off-topic (politics, personal life, etc.), gently steer back to football.
- Never claim to have real-time data you don't have. If asked about live odds or stats, say you're going off general form and tactical read.
- If a "LIVE CONTEXT" block is provided below the persona instructions, treat it as authoritative real-time data about the user's FPL mini-league (standings, rival squads, predicted xPoints, suggested swaps). Use it to give pointed, competitive advice — exposing weak spots in rivals' XIs, suggesting differentials, recommending captain/transfer plays that beat specific managers in the league.

Always reply in character as Liam Rosenior. Do not break character. Do not mention that you are an AI."""


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: str | None = None  # extra context appended to system prompt (e.g. league standings)


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Forward a chat history to Gemini with the Liam Rosenior persona."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not set on the server.",
        )
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    # Convert chat history to Gemini contents schema.
    contents: list[dict] = []
    for m in req.messages:
        role = "user" if m.role == "user" else "model"
        text = (m.content or "").strip()
        if not text:
            continue
        contents.append({"role": role, "parts": [{"text": text}]})
    if not contents:
        raise HTTPException(status_code=400, detail="no non-empty messages")

    system_prompt = ROSENIOR_SYSTEM_PROMPT
    if req.context and req.context.strip():
        # Trim very large contexts to keep token usage sane.
        ctx = req.context.strip()
        if len(ctx) > 6000:
            ctx = ctx[:6000] + "\n…(truncated)"
        system_prompt = (
            ROSENIOR_SYSTEM_PROMPT
            + "\n\n---\nLIVE CONTEXT (use this when relevant to the user's question):\n"
            + ctx
        )

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.85,
            "topP": 0.95,
            "maxOutputTokens": 600,
        },
    }
    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {e}")

    if resp.status_code != 200:
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="Liam's catching his breath — Gemini rate limit hit. Try again in a minute.",
            )
        raise HTTPException(
            status_code=502,
            detail=f"Gemini error {resp.status_code}: {resp.text[:300]}",
        )

    data = resp.json()
    try:
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected Gemini response: {str(data)[:300]}",
        )
    return {"reply": reply.strip()}
