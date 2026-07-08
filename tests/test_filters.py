"""Unit tests for the reviewer freshness filters:
  - drop candidates who haven't published in the last N years (default 3)
  - drop candidates whose most recent MATCHING paper is > M years old (default 15)

Run directly or under pytest:
    python tests/test_filters.py
    python -m pytest tests/test_filters.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewer_id.score import (
    last_publication_year, is_stale_activity, is_related_paper_too_old)


def _cby(*year_count_pairs):
    return {"counts_by_year": [{"year": y, "works_count": c} for y, c in year_count_pairs]}


# ---- last_publication_year: newest year with real output, else None ----
def test_last_publication_year():
    assert last_publication_year(_cby((2020, 3), (2024, 1))) == 2024
    # a year present but with 0 works doesn't count as activity
    assert last_publication_year(_cby((2025, 0), (2022, 2))) == 2022
    assert last_publication_year({"counts_by_year": []}) is None
    assert last_publication_year({}) is None
    assert last_publication_year(None) is None


# ---- "hasn't published in 3 years or more" -> drop ----
def test_is_stale_activity():
    cy = 2026
    # last pub 2024 (gap 2) -> still active, kept
    assert not is_stale_activity(_cby((2024, 1)), cy, 3)
    # last pub 2023 (gap 3) -> "3 years or more" -> stale, dropped
    assert is_stale_activity(_cby((2023, 1)), cy, 3)
    # last pub 2022 (gap 4) -> stale
    assert is_stale_activity(_cby((2019, 5), (2022, 2)), cy, 3)
    # no year data -> we don't guess -> not stale (kept)
    assert not is_stale_activity({}, cy, 3)
    # max_gap of 0/None disables the filter
    assert not is_stale_activity(_cby((2000, 9)), cy, 0)
    assert not is_stale_activity(_cby((2000, 9)), cy, None)


# ---- "related paper more than 15 years old" -> drop ----
def test_is_related_paper_too_old():
    cy = 2026
    # newest match 2011 (age 15) -> kept (not MORE than 15 years old)
    assert not is_related_paper_too_old(2011, cy, 15)
    # newest match 2010 (age 16) -> dropped
    assert is_related_paper_too_old(2010, cy, 15)
    # the "wrote something in 1995" case from the request -> dropped
    assert is_related_paper_too_old(1995, cy, 15)
    # a recent match -> kept
    assert not is_related_paper_too_old(2024, cy, 15)
    # no year on the matched work -> can't judge -> kept
    assert not is_related_paper_too_old(None, cy, 15)
    # max_age of 0/None disables the filter
    assert not is_related_paper_too_old(1995, cy, 0)
    assert not is_related_paper_too_old(1995, cy, None)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
