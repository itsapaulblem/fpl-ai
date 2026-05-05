"""Phase 10 — backtest harness tests.

Uses the same synthetic vaastav cache trick as test_historical, then runs a
mini backtest end-to-end to confirm wiring.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import historical as hist
from src.backtest import BacktestReport, run_backtest


def _toy_players(n: int = 30) -> pd.DataFrame:
    # Need enough players + spread of element_type for the model to fit
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "id": i,
            "first_name": f"F{i}",
            "second_name": f"L{i}",
            "web_name": f"P{i}",
            "team": (i % 4) + 1,
            "element_type": ((i - 1) % 4) + 1,
            "now_cost": 50 + (i % 30),
        })
    return pd.DataFrame(rows)


def _toy_teams(k: int = 4) -> pd.DataFrame:
    return pd.DataFrame([
        {"id": t, "name": f"Team{t}", "short_name": f"T{t}", "strength": 3,
         "strength_overall_home": 1100, "strength_overall_away": 1080,
         "strength_attack_home": 1100, "strength_attack_away": 1080,
         "strength_defence_home": 1100, "strength_defence_away": 1080}
        for t in range(1, k + 1)
    ])


def _toy_history(player_ids, n_gws: int = 20) -> pd.DataFrame:
    rows = []
    for pid in player_ids:
        for gw in range(1, n_gws + 1):
            rows.append({
                "element": pid,
                "GW": gw,
                "opponent_team": ((pid + gw) % 4) + 1,
                "was_home": gw % 2,
                "minutes": 60 + (pid + gw) % 30,
                "total_points": (pid + gw) % 12,
                "bps": 10 + (pid + gw) % 20,
                "ict_index": float(5 + (pid + gw) % 7),
                "value": 50 + pid,
                "expected_goal_involvements": 0.3,
                "expected_goals_conceded": 1.0,
                "goals_scored": 0,
                "assists": 0,
                "clean_sheets": 0,
            })
    return pd.DataFrame(rows)


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    cache = tmp_path / "vaastav"
    monkeypatch.setattr(hist, "EXTERNAL_DIR", cache)
    seasons = ["S1", "S2", "S3"]
    for season in seasons:
        d = cache / season
        d.mkdir(parents=True)
        players = _toy_players()
        teams = _toy_teams()
        history = _toy_history(players["id"].tolist())
        players.to_csv(d / "players_raw.csv", index=False)
        teams.to_csv(d / "teams.csv", index=False)
        history.to_csv(d / "merged_gw.csv", index=False)
    return cache, seasons


def test_run_backtest_produces_per_gw_results(fake_cache):
    _, seasons = fake_cache
    report = run_backtest(
        test_season=seasons[2],
        train_seasons=[seasons[0], seasons[1]],
        start_gw=5,
        end_gw=10,
    )
    assert isinstance(report, BacktestReport)
    df = report.to_frame()
    assert len(df) == 6  # GW 5..10 inclusive
    assert {"gw", "rmse", "mae", "ai_xi_points",
            "form_xi_points", "captain_id"}.issubset(df.columns)
    # Sanity: ai_xi should beat random more often than not
    assert df["ai_xi_points"].mean() > 0


def test_summary_has_aggregate_metrics(fake_cache):
    _, seasons = fake_cache
    report = run_backtest(
        test_season=seasons[2],
        train_seasons=[seasons[0], seasons[1]],
        start_gw=5,
        end_gw=8,
    )
    summary = report.summary()
    for key in ("rmse_mean", "mae_mean", "ai_xi_total",
                "form_xi_total", "ai_vs_form_pct"):
        assert key in summary
    assert summary["n_gws"] == 4


def test_empty_test_season_raises(fake_cache, monkeypatch):
    _, seasons = fake_cache
    # Patch the per-season builder to return empty
    import src.backtest as bt
    monkeypatch.setattr(bt, "_build_test_season_features",
                        lambda s: pd.DataFrame())
    with pytest.raises(ValueError):
        run_backtest(test_season=seasons[2],
                     train_seasons=[seasons[0]], start_gw=5, end_gw=8)


def test_skips_missing_gws(fake_cache):
    _, seasons = fake_cache
    # Ask for GWs that don't exist in toy data (only 1..20)
    report = run_backtest(
        test_season=seasons[2],
        train_seasons=[seasons[0]],
        start_gw=25,
        end_gw=30,
    )
    assert report.to_frame().empty
    assert report.summary()["n_gws"] == 0
