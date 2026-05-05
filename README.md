# FPL AI — Gameweek Squad Recommender

A machine-learning system that recommends an optimal Fantasy Premier League (FPL) squad for the upcoming gameweek by:

1. **Pulling live data** from the official FPL public API (players, fixtures, per-gameweek histories).
2. **Engineering features** (rolling form, ICT index, expected goal involvements, opponent strength, home/away).
3. **Training a gradient-boosted regressor** (LightGBM) to predict each player's expected points (`xPoints`) for the next gameweek.
4. **Solving an Integer Linear Program** (PuLP / CBC) to pick the legal 15-man squad and 11-man starting XI that maximise total `xPoints` under FPL constraints (£100m budget, 2/5/5/3 by position, max 3 per club, valid formations).
5. **Suggesting transfers** from your current team, accounting for the −4 hit per extra transfer.

> Built as an end-to-end portfolio project — covers data engineering, ML modelling, mathematical optimisation, and CLI delivery.

---

## Quick start

```powershell
# 1. Create a virtual environment (Windows / PowerShell)
python -m venv .venv
. .venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the recommender (fetches data, trains model, prints squad)
python main.py

# Plan over the next 3 gameweeks
python main.py --horizon 3

# Personalised transfer suggestions for your team (find your manager id in the FPL site URL)
python main.py --team-id 123456
```

The first run takes a few minutes — it pulls per-player history for ~600 players from the FPL API. Subsequent runs reuse the cached parquet files in `data/processed/`.

---

## Project layout

```
fpl-ai/
├── main.py                  # CLI entry point
├── requirements.txt
├── src/
│   ├── fpl_api.py           # Thin wrapper over the FPL public API
│   ├── data_loader.py       # Fetch + assemble training set
│   ├── model.py             # LightGBM xPoints model (with sklearn fallback)
│   ├── optimizer.py         # ILP for squad / XI / transfer suggestions
│   └── recommend.py         # End-to-end pipeline + report formatter
├── tests/
│   └── test_optimizer.py    # Constraint validation (no network needed)
└── data/  models/           # Generated artifacts (gitignored)
```

---

## How the model works

**Target.** `total_points` scored by a player in a given gameweek (the official FPL points).

**Features (only information available *before* kickoff):**

| Group | Features |
| --- | --- |
| Recent form | `minutes`, `total_points`, `bps`, `ict_index` lag-1 + rolling 3 / 5 GW means |
| Underlying stats | `expected_goal_involvements`, `expected_goals_conceded` lag-1 + rolling 3 |
| Fixture | `is_home`, `opp_strength`, opponent attack/defence ratings |
| Player meta | `element_type` (position), team strength ratings |

**Validation.** A time-based split (last 4 GWs as the validation set) is used so the model is never evaluated on the past, mirroring real-world deployment.

**Inference.** For every active player, the latest lagged features are joined with their next fixture(s), the model predicts `xPoints`, and these are summed across the optimisation horizon.

---

## How the optimiser works

A binary ILP (solved by CBC via PuLP):

- **Variables:** $x_i \in \{0, 1\}$ for each player.
- **Objective:** $\max \sum_i x_i \cdot \text{xPoints}_i$
- **Constraints:**
  - $\sum_i x_i \cdot \text{price}_i \le 100$
  - Exactly 2 GK, 5 DEF, 5 MID, 3 FWD selected
  - $\sum_{i \in \text{club}} x_i \le 3$ for every Premier League club
- A second ILP picks the 11-man starting XI from the chosen 15 under FPL formation rules; the highest-`xPoints` starter becomes captain (doubled).

For transfers, each held player is paired with the best affordable upgrade in the same position; the −4 hit is subtracted beyond the free-transfer allowance and suggestions are ranked by **net** `xPoints` gain.

---

## Run the tests

```powershell
pytest -q
```

The included tests verify the optimiser respects every FPL constraint on a synthetic player pool (no network needed).

---

## Roadmap / extensions (good talking points for interviews)

- Multi-GW joint optimisation with transfer planning over a horizon (currently transfers are greedy 1-for-1).
- Bayesian uncertainty estimates on `xPoints` and risk-adjusted selection.
- Wildcard / Bench Boost / Triple Captain chip recommendation.
- Backtesting harness across past seasons (data available via the `vaastav/Fantasy-Premier-League` GitHub dataset).
- Replace LightGBM with a player-embedding neural net for cold-start handling.

---

## Credits

- [Fantasy Premier League public API](https://fantasy.premierleague.com/api/) — official data source.
- LightGBM, scikit-learn, PuLP / CBC — modelling & optimisation stack.
