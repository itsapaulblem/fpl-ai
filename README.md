# Paul FPL AI

An end-to-end machine-learning + optimisation system that recommends an optimal
Fantasy Premier League squad each gameweek.

> 🚧 **Work in progress.** Building this in phases — see the roadmap below.

## Pipeline (planned)

```
[FPL API + vaastav CSVs]  →  [Features]  →  [LightGBM]  →  [ILP optimiser]  →  [Web UI]
       raw data              engineered      xPoints         legal squad         deployed
```

## Roadmap

- [x] **Phase 1** — Project skeleton & dependencies
- [ ] **Phase 2** — Explore the FPL public API
- [ ] **Phase 3** — `FPLClient` wrapper
- [ ] **Phase 4** — Data loader & feature engineering
- [ ] **Phase 5** — LightGBM xPoints model
- [ ] **Phase 6** — Integer linear program for squad selection
- [ ] **Phase 7** — Tests
- [ ] **Phase 8** — CLI entry point
- [ ] **Phase 9** — Train on `vaastav/Fantasy-Premier-League` historical seasons
- [ ] **Phase 10** — Backtest vs. average manager
- [ ] **Phase 11** — FastAPI + Streamlit UI
- [ ] **Phase 12** — Deploy to AWS

## Quick start

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

## Project layout

```
fpl-ai/
├── src/              # library code (api client, model, optimiser)
├── tests/            # pytest suite
├── notebooks/        # Jupyter exploration
├── data/             # downloaded data (gitignored)
├── models/           # trained model artifacts (gitignored)
├── main.py           # CLI entry point
├── requirements.txt
└── README.md
```
