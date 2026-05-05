"""Phase 6 — Squad optimizer (Integer Linear Programming).

Given each player's predicted xPoints (from `src.model.predict_next_gw`)
choose the best legal FPL squad:

Squad rules:
    - 15 players total
    - 2 GK, 5 DEF, 5 MID, 3 FWD
    - Total price <= budget (default £100.0m)
    - Max 3 players per real-world club

Then pick the starting XI (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD; total 11)
that maximises xPoints, plus a captain (2x multiplier).

We solve it with PuLP + the bundled CBC solver — exact optimum, fast
(< 1 second for ~600 players).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import pulp

# ---------------------------------------------------------------------- #
# FPL constants
# ---------------------------------------------------------------------- #
SQUAD_SIZE = 15
STARTING_XI = 11
DEFAULT_BUDGET = 100.0
MAX_PER_CLUB = 3

POSITION_QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}

# Min/max each position can field in the starting XI
XI_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
XI_MAX = {"GKP": 1, "DEF": 5, "MID": 5, "FWD": 3}

REQUIRED_COLS = ("player_id", "position", "team", "price", "xPoints")


# ---------------------------------------------------------------------- #
# Result types
# ---------------------------------------------------------------------- #
@dataclass
class SquadSelection:
    squad: pd.DataFrame              # 15 rows
    starting_xi: pd.DataFrame        # 11 rows (subset of squad)
    bench: pd.DataFrame              # 4 rows
    captain_id: int
    vice_captain_id: int
    total_xpoints: float             # XI sum + captain bonus
    total_cost: float
    formation: str                   # e.g. "3-4-3"


# ---------------------------------------------------------------------- #
# Validation
# ---------------------------------------------------------------------- #
def _check_inputs(players: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLS if c not in players.columns]
    if missing:
        raise ValueError(f"players is missing required columns: {missing}")
    df = players.dropna(subset=list(REQUIRED_COLS)).copy()
    df = df[df["position"].isin(POSITION_QUOTAS)]
    if df.empty:
        raise ValueError("No eligible players after filtering on required columns.")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Squad selection (15 players)
# ---------------------------------------------------------------------- #
def select_squad(
    players: pd.DataFrame,
    budget: float = DEFAULT_BUDGET,
    max_per_club: int = MAX_PER_CLUB,
    must_include: Iterable[int] | None = None,
    must_exclude: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Pick the legal 15-man squad that maximises sum of xPoints.

    `players` must have columns: player_id, position, team, price, xPoints.
    """
    df = _check_inputs(players)
    if must_exclude:
        df = df[~df["player_id"].isin(set(must_exclude))].reset_index(drop=True)

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)

    # Binary "in squad?" var for each player
    pick = {
        int(row.player_id): pulp.LpVariable(f"x_{int(row.player_id)}", cat="Binary")
        for row in df.itertuples()
    }

    # Objective: maximise total xPoints across the 15
    prob += pulp.lpSum(pick[int(r.player_id)] * float(r.xPoints) for r in df.itertuples())

    # Squad size
    prob += pulp.lpSum(pick.values()) == SQUAD_SIZE

    # Position quotas
    for pos, n in POSITION_QUOTAS.items():
        prob += pulp.lpSum(
            pick[int(r.player_id)] for r in df.itertuples() if r.position == pos
        ) == n

    # Budget
    prob += pulp.lpSum(
        pick[int(r.player_id)] * float(r.price) for r in df.itertuples()
    ) <= budget

    # Max per club
    for team_id in df["team"].unique():
        prob += pulp.lpSum(
            pick[int(r.player_id)] for r in df.itertuples() if r.team == team_id
        ) <= max_per_club

    # Forced picks
    for pid in (must_include or []):
        if pid in pick:
            prob += pick[pid] == 1

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(
            f"Squad ILP did not find an optimal solution (status={pulp.LpStatus[status]}). "
            "Try increasing the budget or relaxing constraints."
        )

    chosen_ids = [pid for pid, var in pick.items() if var.value() > 0.5]
    return df[df["player_id"].isin(chosen_ids)].reset_index(drop=True)


# ---------------------------------------------------------------------- #
# Starting XI + captain (within the chosen 15)
# ---------------------------------------------------------------------- #
def pick_starting_xi(squad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """From a 15-man squad, pick the legal XI that maximises xPoints."""
    prob = pulp.LpProblem("fpl_xi", pulp.LpMaximize)
    start = {
        int(r.player_id): pulp.LpVariable(f"s_{int(r.player_id)}", cat="Binary")
        for r in squad.itertuples()
    }

    prob += pulp.lpSum(
        start[int(r.player_id)] * float(r.xPoints) for r in squad.itertuples()
    )
    prob += pulp.lpSum(start.values()) == STARTING_XI
    for pos, lo in XI_MIN.items():
        hi = XI_MAX[pos]
        in_pos = [start[int(r.player_id)] for r in squad.itertuples() if r.position == pos]
        prob += pulp.lpSum(in_pos) >= lo
        prob += pulp.lpSum(in_pos) <= hi

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"XI ILP failed (status={pulp.LpStatus[status]})")

    starter_ids = {pid for pid, var in start.items() if var.value() > 0.5}
    xi = squad[squad["player_id"].isin(starter_ids)].reset_index(drop=True)
    bench = squad[~squad["player_id"].isin(starter_ids)].reset_index(drop=True)

    counts = xi["position"].value_counts().to_dict()
    formation = f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"
    return xi, bench, formation



# ---------------------------------------------------------------------- #
# All-in-one
# ---------------------------------------------------------------------- #
def pick_team(
    players: pd.DataFrame,
    budget: float = DEFAULT_BUDGET,
    max_per_club: int = MAX_PER_CLUB,
    must_include: Iterable[int] | None = None,
    must_exclude: Iterable[int] | None = None,
) -> SquadSelection:
    """Full pipeline: 15-man squad → starting XI → captain (highest xP starter)."""
    squad = select_squad(
        players,
        budget=budget,
        max_per_club=max_per_club,
        must_include=must_include,
        must_exclude=must_exclude,
    )
    xi, bench, formation = pick_starting_xi(squad)

    xi_sorted = xi.sort_values("xPoints", ascending=False).reset_index(drop=True)
    captain_id = int(xi_sorted.iloc[0]["player_id"])
    vice_id = int(xi_sorted.iloc[1]["player_id"])

    total_xp = float(xi["xPoints"].sum() + xi_sorted.iloc[0]["xPoints"])  # +1x for captain
    total_cost = float(squad["price"].sum())

    # Tag rows for clarity
    squad = squad.copy()
    squad["is_starter"] = squad["player_id"].isin(set(xi["player_id"]))
    squad["is_captain"] = squad["player_id"] == captain_id
    squad["is_vice"] = squad["player_id"] == vice_id

    return SquadSelection(
        squad=squad,
        starting_xi=xi,
        bench=bench,
        captain_id=captain_id,
        vice_captain_id=vice_id,
        total_xpoints=total_xp,
        total_cost=total_cost,
        formation=formation,
    )


def format_team(sel: SquadSelection) -> str:
    """Pretty-print a SquadSelection for the CLI."""
    cols = [c for c in ("web_name", "team_name", "position", "price", "xPoints")
            if c in sel.squad.columns]
    rename = {"web_name": "player", "team_name": "team"}

    def _fmt(df):
        return df[cols].rename(columns=rename).to_string(index=False)

    cap_row = sel.starting_xi[sel.starting_xi["player_id"] == sel.captain_id].iloc[0]
    vice_row = sel.starting_xi[sel.starting_xi["player_id"] == sel.vice_captain_id].iloc[0]
    cap_name = cap_row.get("web_name", sel.captain_id)
    vice_name = vice_row.get("web_name", sel.vice_captain_id)

    lines = [
        f"Formation: {sel.formation}    Cost: £{sel.total_cost:.1f}m    xPoints: {sel.total_xpoints:.2f}",
        "",
        "Starting XI:",
        _fmt(sel.starting_xi.sort_values(["position", "xPoints"], ascending=[True, False])),
        "",
        "Bench:",
        _fmt(sel.bench.sort_values("xPoints", ascending=False)),
        "",
        f"Captain (2x):    {cap_name}",
        f"Vice-captain:    {vice_name}",
    ]
    return "\n".join(lines)


__all__ = [
    "SquadSelection",
    "POSITION_QUOTAS",
    "DEFAULT_BUDGET",
    "select_squad",
    "pick_starting_xi",
    "pick_team",
    "format_team",
]
