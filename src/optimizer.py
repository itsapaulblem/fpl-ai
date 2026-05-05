"""Squad selection via Integer Linear Programming.

FPL squad rules:
- 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD
- Budget: 100.0m (configurable)
- Max 3 players per Premier League club
- Starting XI: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD (11 players total)
- Captain: doubles points (we model by selecting captain among XI)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pulp

POSITION_REQ_SQUAD = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
POSITION_REQ_XI_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
POSITION_REQ_XI_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}


@dataclass
class SquadResult:
    squad: pd.DataFrame      # 15 players
    starting_xi: pd.DataFrame  # 11 players, 'is_captain' & 'is_vice' marked
    expected_points: float
    total_cost: float


def _normalize_position(pos: str) -> str:
    pos = (pos or "").upper()
    if pos in {"GK", "GKP"}:
        return "GKP"
    return pos


def pick_squad(
    players: pd.DataFrame,
    budget: float = 100.0,
    must_include: list[int] | None = None,
    must_exclude: list[int] | None = None,
) -> SquadResult:
    """Pick the optimal 15-man squad maximising sum of xPoints.

    `players` must have columns: player_id, web_name, team, team_name,
    position, price, xPoints.
    """
    df = players.copy()
    df["position"] = df["position"].map(_normalize_position)
    df = df[df["position"].isin(POSITION_REQ_SQUAD)].reset_index(drop=True)
    must_include = must_include or []
    must_exclude = must_exclude or []
    df = df[~df["player_id"].isin(must_exclude)].reset_index(drop=True)

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {
        int(row.player_id): pulp.LpVariable(f"x_{int(row.player_id)}", cat="Binary")
        for row in df.itertuples()
    }

    # Objective: maximise xPoints
    prob += pulp.lpSum(x[int(r.player_id)] * float(r.xPoints) for r in df.itertuples())

    # Budget
    prob += pulp.lpSum(x[int(r.player_id)] * float(r.price) for r in df.itertuples()) <= budget

    # Position counts
    for pos, req in POSITION_REQ_SQUAD.items():
        prob += pulp.lpSum(
            x[int(r.player_id)] for r in df.itertuples() if r.position == pos
        ) == req

    # Squad size
    prob += pulp.lpSum(x.values()) == 15

    # Max 3 per club
    for team_id in df["team"].unique():
        prob += pulp.lpSum(
            x[int(r.player_id)] for r in df.itertuples() if r.team == team_id
        ) <= 3

    # Forced inclusions
    for pid in must_include:
        if pid in x:
            prob += x[pid] == 1

    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"Squad LP not optimal: {pulp.LpStatus[status]}")

    chosen_ids = [pid for pid, var in x.items() if var.value() > 0.5]
    squad = df[df["player_id"].isin(chosen_ids)].copy()

    xi = pick_starting_xi(squad)
    captain_id = xi.sort_values("xPoints", ascending=False).iloc[0]["player_id"]
    vice_id = xi.sort_values("xPoints", ascending=False).iloc[1]["player_id"]
    xi["is_captain"] = xi["player_id"] == captain_id
    xi["is_vice"] = xi["player_id"] == vice_id

    expected = float(xi["xPoints"].sum() + xi.loc[xi["is_captain"], "xPoints"].sum())
    cost = float(squad["price"].sum())

    squad = squad.sort_values(
        ["position", "xPoints"], ascending=[True, False]
    ).reset_index(drop=True)
    xi = xi.sort_values(["position", "xPoints"], ascending=[True, False]).reset_index(drop=True)
    return SquadResult(squad=squad, starting_xi=xi, expected_points=expected, total_cost=cost)


def pick_starting_xi(squad: pd.DataFrame) -> pd.DataFrame:
    """Choose 11 starters from a 15-man squad maximising xPoints."""
    df = squad.copy().reset_index(drop=True)
    prob = pulp.LpProblem("fpl_xi", pulp.LpMaximize)
    y = {
        int(r.player_id): pulp.LpVariable(f"y_{int(r.player_id)}", cat="Binary")
        for r in df.itertuples()
    }
    prob += pulp.lpSum(y[int(r.player_id)] * float(r.xPoints) for r in df.itertuples())
    prob += pulp.lpSum(y.values()) == 11

    for pos, mn in POSITION_REQ_XI_MIN.items():
        prob += pulp.lpSum(
            y[int(r.player_id)] for r in df.itertuples() if r.position == pos
        ) >= mn
    for pos, mx in POSITION_REQ_XI_MAX.items():
        prob += pulp.lpSum(
            y[int(r.player_id)] for r in df.itertuples() if r.position == pos
        ) <= mx

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    chosen = [pid for pid, var in y.items() if var.value() > 0.5]
    return df[df["player_id"].isin(chosen)].copy()


def recommend_transfers(
    current_squad_ids: list[int],
    players: pd.DataFrame,
    free_transfers: int = 1,
    hit_cost: int = 4,
    budget: float = 100.0,
) -> pd.DataFrame:
    """Suggest up to N transfers that maximise net xPoints gain.

    Net gain = (sum xPoints of players IN) - (sum xPoints of players OUT)
               - hit_cost * max(0, transfers - free_transfers)
    """
    df = players.copy()
    df["position"] = df["position"].map(_normalize_position)
    in_squad = df[df["player_id"].isin(current_squad_ids)].copy()
    if in_squad.empty:
        return pd.DataFrame(columns=["out", "in", "delta_xPoints"])

    bank = budget - in_squad["price"].sum()
    suggestions = []
    for pos in POSITION_REQ_SQUAD:
        held = in_squad[in_squad["position"] == pos]
        candidates = df[
            (df["position"] == pos) & (~df["player_id"].isin(current_squad_ids))
        ]
        for h in held.itertuples():
            affordable = candidates[candidates["price"] <= h.price + bank]
            if affordable.empty:
                continue
            best = affordable.sort_values("xPoints", ascending=False).iloc[0]
            delta = float(best["xPoints"]) - float(h.xPoints)
            suggestions.append({
                "out_id": int(h.player_id), "out_name": h.web_name,
                "out_xP": float(h.xPoints), "out_price": float(h.price),
                "in_id": int(best["player_id"]), "in_name": best["web_name"],
                "in_xP": float(best["xPoints"]), "in_price": float(best["price"]),
                "delta_xPoints": delta,
            })
    sug = pd.DataFrame(suggestions).sort_values("delta_xPoints", ascending=False)
    if sug.empty:
        return sug
    sug["net_delta"] = sug["delta_xPoints"].copy()
    extra = max(0, len(sug) - free_transfers)
    if extra:
        sug.iloc[free_transfers:, sug.columns.get_loc("net_delta")] -= hit_cost
    return sug
