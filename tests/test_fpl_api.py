"""Unit tests for src.fpl_api helpers — no network required."""
from src.fpl_api import current_gameweek, next_gameweek


def _events(*, current=None, next_=None, count=38):
    """Build a minimal fake bootstrap['events'] list."""
    out = []
    for i in range(1, count + 1):
        out.append({
            "id": i,
            "is_current": i == current,
            "is_next": i == next_,
        })
    return {"events": out}


def test_current_gameweek_picks_is_current():
    assert current_gameweek(_events(current=12, next_=13)) == 12


def test_current_gameweek_falls_back_to_is_next():
    # Pre-season: nothing is current yet.
    assert current_gameweek(_events(next_=1)) == 1


def test_current_gameweek_falls_back_to_first():
    # No current, no next (degenerate).
    assert current_gameweek(_events()) == 1


def test_next_gameweek_prefers_is_next():
    assert next_gameweek(_events(current=20, next_=21)) == 21


def test_next_gameweek_increments_current():
    # No is_next flag — should be current + 1.
    assert next_gameweek(_events(current=20)) == 21


def test_next_gameweek_caps_at_38():
    assert next_gameweek(_events(current=38)) == 38
