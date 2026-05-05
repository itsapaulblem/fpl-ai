"""Phase 7 — Transfer planner.

Given:
    - your current 15-man squad (player_ids + purchase prices)
    - this gameweek's xPoints predictions
    - your free transfers and bank balance

Find the 0/1/2 transfer combination that maximises:

    sum(xPoints of new starting XI)  -  4 * max(0, n_transfers - free_transfers)

while keeping the resulting squad legal (15 players, position quotas,
budget, ≤3 per club).

We brute-force enumerate candidate (out, in) pairs because the search space
is tiny:
    - 1 transfer: 15 outs * ~50 plausible ins  ≈ 750
    - 2 transfers: ~750 * ~750  ≈ half a million, but we prune aggressively
      by only considering swaps that *gain* xPoints and stay within budget.

For each candidate we run the Phase 6 starting-XI ILP — that part is sub-ms
on 15 players, so the whole planner finishes in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable

import pandas as pd

from .optimizer import (
    DEFAULT_BUDGET,
    MAX_PER_CLUB,
    POSITION_QUOTAS,
    pick_starting_xi,
)

HIT_COST = 4  # FPL deducts 4 points per extra transfer beyond your free count


# ---------------------------------------------------------------------- #
# Public types
# ---------------------------------------------------------------------- #
@dataclass
class TransferPlan:
    """One concrete transfer suggestion."""
    transfers_out: list[int]              # player_ids leaving the squad
    transfers_in: list[int]               # player_ids joining the squad
    n_transfers: int
    hit_cost: int                         # points deducted (0 / 4 / 8 / ...)
    xi_xpoints: float                     # XI total (incl. captain) BEFORE hit
    net_xpoints: float                    # xi_xpoints - hit_cost
    bank_after: float                     # money remaining after the swap
    new_squad: pd.DataFrame               # the 15 after the swap
    new_xi: pd.DataFrame
    formation: str
    captain_id: int


@dataclass
class TransferReport:
    """The full ranked output: doing nothing vs. each suggested plan."""
    baseline: TransferPlan                # 0 transfers
    plans: list[TransferPlan] = field(default_factory=list)  # sorted by net_xp desc

    def best(self) -> TransferPlan:
        candidates = [self.baseline, *self.plans]
        return max(candidates, key=lambda p: p.net_xpoints)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _evaluate_squad(squad: pd.DataFrame) -> tuple[float, pd.DataFrame, str, int]:
    """Pick the best XI + captain for a 15-man squad. Returns (xi_xp, xi, formation, captain_id)."""
    xi, _bench, formation = pick_starting_xi(squad)
    captain_xp = float(xi["xPoints"].max())
    captain_id = int(xi.sort_values("xPoints", ascending=False).iloc[0]["player_id"])
    xi_xp = float(xi["xPoints"].sum() + captain_xp)
    return xi_xp, xi, formation, captain_id


def _is_legal(squad: pd.DataFrame, max_per_club: int) -> bool:
    if len(squad) != 15:
        return False
    counts = squad["position"].value_counts().to_dict()
    for pos, n in POSITION_QUOTAS.items():
        if counts.get(pos, 0) != n:
            return False
    if squad["team"].value_counts().max() > max_per_club:
        return False
    return True


def _candidate_pool(
    predictions: pd.DataFrame,
    current_ids: set[int],
    pool_size: int = 60,
) -> pd.DataFrame:
    """Top-N players (by xPoints) that aren't already in the squad,
    keeping a healthy mix per position."""
    pool_parts = []
    others = predictions[~predictions["player_id"].isin(current_ids)]
    for pos in POSITION_QUOTAS:
        pool_parts.append(
            others[others["position"] == pos].nlargest(pool_size, "xPoints")
        )
    return pd.concat(pool_parts, ignore_index=True)


# ---------------------------------------------------------------------- #
# Public API
# ---------------------------------------------------------------------- #
def plan_transfers(
    current_squad: pd.DataFrame,
    predictions: pd.DataFrame,
    bank: float = 0.0,
    free_transfers: int = 1,
    max_transfers: int = 2,
    max_per_club: int = MAX_PER_CLUB,
    pool_size: int = 60,
    top_k: int = 5,
) -> TransferReport:
    """Find the best 0..max_transfers moves for the upcoming gameweek.

    `current_squad` must include columns: player_id, position, team,
        purchase_price, selling_price.
    `predictions` is the output of `model.predict_next_gw` (player_id,
        position, team, price, xPoints, ...).
    `bank` is unspent money in £m.
    `free_transfers` is your available free transfers (0, 1, or 2).
    """
    required = {"player_id", "position", "team"}
    if not required.issubset(current_squad.columns):
        raise ValueError(f"current_squad missing columns: {required - set(current_squad.columns)}")
    if "selling_price" not in current_squad.columns:
        # Fall back to current price if the user doesn't provide it.
        current_squad = current_squad.assign(selling_price=current_squad.get("price", 0.0))

    # Attach xPoints (and current market price) from predictions, dropping any
    # stale copies on the squad first so the merge doesn't create _x/_y columns.
    squad_clean = current_squad.drop(
        columns=[c for c in ("xPoints", "price") if c in current_squad.columns],
        errors="ignore",
    )
    pred_cols = ["player_id", "xPoints"]
    if "price" in predictions.columns:
        pred_cols.append("price")
    enriched = squad_clean.merge(predictions[pred_cols], on="player_id", how="left")
    enriched["xPoints"] = enriched["xPoints"].fillna(0.0)
    if "price" not in enriched.columns:
        enriched["price"] = enriched["selling_price"]

    current_ids = set(int(p) for p in enriched["player_id"])

    # ---- baseline: do nothing ----
    base_xp, base_xi, base_form, base_cap = _evaluate_squad(enriched)
    baseline = TransferPlan(
        transfers_out=[], transfers_in=[],
        n_transfers=0, hit_cost=0,
        xi_xpoints=base_xp, net_xpoints=base_xp,
        bank_after=bank,
        new_squad=enriched, new_xi=base_xi,
        formation=base_form, captain_id=base_cap,
    )

    pool = _candidate_pool(predictions, current_ids, pool_size=pool_size)

    plans: list[TransferPlan] = []

    # ---- 1-transfer search ----
    if max_transfers >= 1:
        for _, out_row in enriched.iterrows():
            out_pos = out_row["position"]
            out_id = int(out_row["player_id"])
            out_sell = float(out_row["selling_price"])
            out_xp = float(out_row["xPoints"])
            budget = bank + out_sell

            candidates = pool[(pool["position"] == out_pos) & (pool["price"] <= budget)]
            # Only consider in-players that score *more* than the player they replace.
            candidates = candidates[candidates["xPoints"] > out_xp]

            for _, in_row in candidates.iterrows():
                in_id = int(in_row["player_id"])
                new_squad = pd.concat([
                    enriched[enriched["player_id"] != out_id],
                    _row_to_squad_format(in_row, in_id),
                ], ignore_index=True)
                if not _is_legal(new_squad, max_per_club):
                    continue
                xi_xp, xi, form, cap = _evaluate_squad(new_squad)
                hit = HIT_COST * max(0, 1 - free_transfers)
                net = xi_xp - hit
                if net <= base_xp:
                    continue
                plans.append(TransferPlan(
                    transfers_out=[out_id], transfers_in=[in_id],
                    n_transfers=1, hit_cost=hit,
                    xi_xpoints=xi_xp, net_xpoints=net,
                    bank_after=budget - float(in_row["price"]),
                    new_squad=new_squad, new_xi=xi,
                    formation=form, captain_id=cap,
                ))

    # ---- 2-transfer search (pruned) ----
    if max_transfers >= 2:
        # Only consider swap-pairs where each individual swap might be useful.
        # Pre-compute: for each squad slot, the best `top_k` candidates that fit budget alone.
        per_slot_best: dict[int, list[tuple[int, float, float, str, int]]] = {}
        for _, out_row in enriched.iterrows():
            out_id = int(out_row["player_id"])
            cands = pool[
                (pool["position"] == out_row["position"]) &
                (pool["xPoints"] > float(out_row["xPoints"]) - 1.0)  # allow slight downgrades — paired swap may still win
            ].nlargest(top_k, "xPoints")
            per_slot_best[out_id] = [
                (int(c.player_id), float(c.price), float(c.xPoints), c.position, int(c.team))
                for c in cands.itertuples()
            ]

        squad_rows = list(enriched.itertuples())
        for out_a, out_b in combinations(squad_rows, 2):
            ida, idb = int(out_a.player_id), int(out_b.player_id)
            sell_total = float(out_a.selling_price) + float(out_b.selling_price)
            for ina_id, ina_price, ina_xp, ina_pos, ina_team in per_slot_best.get(ida, []):
                for inb_id, inb_price, inb_xp, inb_pos, inb_team in per_slot_best.get(idb, []):
                    if ina_id == inb_id:
                        continue
                    cost = ina_price + inb_price
                    if cost > bank + sell_total + 1e-9:
                        continue
                    # Build the new squad.
                    keep = enriched[~enriched["player_id"].isin({ida, idb})]
                    new_rows = pd.DataFrame([
                        {"player_id": ina_id, "position": ina_pos, "team": ina_team,
                         "price": ina_price, "selling_price": ina_price, "xPoints": ina_xp,
                         "web_name": "", "team_name": ""},
                        {"player_id": inb_id, "position": inb_pos, "team": inb_team,
                         "price": inb_price, "selling_price": inb_price, "xPoints": inb_xp,
                         "web_name": "", "team_name": ""},
                    ])
                    new_squad = pd.concat([keep, new_rows], ignore_index=True)
                    if not _is_legal(new_squad, max_per_club):
                        continue
                    xi_xp, xi, form, cap = _evaluate_squad(new_squad)
                    hit = HIT_COST * max(0, 2 - free_transfers)
                    net = xi_xp - hit
                    if net <= base_xp:
                        continue
                    plans.append(TransferPlan(
                        transfers_out=[ida, idb], transfers_in=[ina_id, inb_id],
                        n_transfers=2, hit_cost=hit,
                        xi_xpoints=xi_xp, net_xpoints=net,
                        bank_after=bank + sell_total - cost,
                        new_squad=new_squad, new_xi=xi,
                        formation=form, captain_id=cap,
                    ))

    # Dedup by (sorted out-set, sorted in-set) — both 1- and 2-transfer paths
    # may surface the same swap.
    seen: dict[tuple, TransferPlan] = {}
    for p in plans:
        key = (tuple(sorted(p.transfers_out)), tuple(sorted(p.transfers_in)))
        if key not in seen or p.net_xpoints > seen[key].net_xpoints:
            seen[key] = p
    unique_plans = sorted(seen.values(), key=lambda p: p.net_xpoints, reverse=True)

    # ---- 3-5 transfer search (greedy iterative on top of best 2-transfer) ----
    # For N > 2 we greedily extend the best plan found so far by applying
    # one more 1-transfer swap at a time. This is fast and finds good
    # (though not provably optimal) solutions.
    if max_transfers >= 3:
        for n_total in range(3, max_transfers + 1):
            # Seed from the best (n_total-1)-transfer plan, or baseline if none.
            candidates_prev = [p for p in unique_plans if p.n_transfers == n_total - 1]
            seed = candidates_prev[0] if candidates_prev else baseline

            current_ids_seed = set(int(p) for p in seed.new_squad["player_id"])
            pool_seed = _candidate_pool(seed.new_squad, current_ids_seed, pool_size=pool_size)

            for _, out_row in seed.new_squad.iterrows():
                out_pos = out_row["position"]
                out_id = int(out_row["player_id"])
                out_sell = float(out_row.get("selling_price", out_row.get("price", 0)))
                out_xp = float(out_row["xPoints"])
                budget = seed.bank_after + out_sell

                cands = pool_seed[
                    (pool_seed["position"] == out_pos) &
                    (pool_seed["price"] <= budget) &
                    (pool_seed["xPoints"] > out_xp)
                ]
                for _, in_row in cands.iterrows():
                    in_id = int(in_row["player_id"])
                    if in_id in {int(p) for p in seed.new_squad["player_id"]}:
                        continue
                    new_squad = pd.concat([
                        seed.new_squad[seed.new_squad["player_id"] != out_id],
                        _row_to_squad_format(in_row, in_id),
                    ], ignore_index=True)
                    if not _is_legal(new_squad, max_per_club):
                        continue
                    xi_xp, xi, form, cap = _evaluate_squad(new_squad)
                    hit = HIT_COST * max(0, n_total - free_transfers)
                    net = xi_xp - hit
                    if net <= base_xp:
                        continue
                    out_ids = list(seed.transfers_out) + [out_id]
                    in_ids = list(seed.transfers_in) + [in_id]
                    plans.append(TransferPlan(
                        transfers_out=out_ids, transfers_in=in_ids,
                        n_transfers=n_total, hit_cost=hit,
                        xi_xpoints=xi_xp, net_xpoints=net,
                        bank_after=budget - float(in_row["price"]),
                        new_squad=new_squad, new_xi=xi,
                        formation=form, captain_id=cap,
                    ))

        # Re-dedup including new greedy plans
        seen = {}
        for p in plans:
            key = (tuple(sorted(p.transfers_out)), tuple(sorted(p.transfers_in)))
            if key not in seen or p.net_xpoints > seen[key].net_xpoints:
                seen[key] = p
        unique_plans = sorted(seen.values(), key=lambda p: p.net_xpoints, reverse=True)

    return TransferReport(baseline=baseline, plans=unique_plans[:20])


def _row_to_squad_format(row: pd.Series, pid: int) -> pd.DataFrame:
    """Coerce a predictions row into the same column layout as `enriched` squad."""
    return pd.DataFrame([{
        "player_id": pid,
        "position": row["position"],
        "team": int(row["team"]),
        "price": float(row["price"]),
        "selling_price": float(row["price"]),
        "xPoints": float(row["xPoints"]),
        "web_name": row.get("web_name", ""),
        "team_name": row.get("team_name", ""),
    }])


# ---------------------------------------------------------------------- #
# Pretty printing + name lookup
# ---------------------------------------------------------------------- #
def format_report(
    report: TransferReport,
    predictions: pd.DataFrame,
    top_n: int = 5,
) -> str:
    """Human-readable summary of the top transfer suggestions."""
    name_map = {int(r.player_id): r.web_name for r in predictions.itertuples()
                if hasattr(r, "web_name")}

    def name(pid: int) -> str:
        return name_map.get(int(pid), f"#{pid}")

    lines = [
        "=" * 70,
        "Baseline (no transfers):",
        f"  XI xPoints: {report.baseline.xi_xpoints:.2f}    "
        f"Captain: {name(report.baseline.captain_id)}    "
        f"Formation: {report.baseline.formation}",
        "",
    ]
    if not report.plans:
        lines.append("No transfer improves on doing nothing. Roll the free transfer.")
        return "\n".join(lines)

    lines.append(f"Top {min(top_n, len(report.plans))} transfer suggestions:")
    for i, p in enumerate(report.plans[:top_n], 1):
        outs = " + ".join(name(x) for x in p.transfers_out)
        ins = " + ".join(name(x) for x in p.transfers_in)
        gain = p.net_xpoints - report.baseline.xi_xpoints
        lines.append(
            f"  {i}. OUT: {outs:30s}  IN: {ins:30s}"
            f"  ΔxP: {gain:+.2f}  (xi={p.xi_xpoints:.2f}, hit={p.hit_cost})"
            f"  bank=£{p.bank_after:.1f}m"
        )

    best = report.best()
    lines += [
        "",
        "=" * 70,
        f"BEST PLAN: {best.n_transfers} transfer(s), net xPoints {best.net_xpoints:.2f} "
        f"(baseline {report.baseline.xi_xpoints:.2f})",
        f"  Captain: {name(best.captain_id)}    Formation: {best.formation}",
    ]
    return "\n".join(lines)


__all__ = [
    "HIT_COST",
    "TransferPlan",
    "TransferReport",
    "plan_transfers",
    "format_report",
]
