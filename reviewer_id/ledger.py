"""Reviewer over-use ledger.

A local, git-ignored file the editor maintains of reviewers who shouldn't be
proposed right now — recently invited (reviewer fatigue), declined, on leave, or
otherwise ineligible in the journal's system. Candidates matching the ledger are
dropped from the results, so the tool stops re-surfacing the same tapped-out names.

Confidential: the ledger lives only on your machine; names are matched locally and
never transmitted anywhere.

CSV columns (all optional except an identifier of some kind):
    name, orcid, openalex_id, last_invited (YYYY-MM-DD), status, note

Exclusion rule for a row:
  * status in {declined, blocked, unavailable, conflict}  -> always excluded
  * no last_invited date                                  -> excluded (on the list for a reason)
  * last_invited within `cooldown_months` of today        -> excluded (cooling down)
  * last_invited older than the cooldown                  -> eligible again
"""

import csv
import re
from datetime import date
from pathlib import Path

PERMANENT = {"declined", "blocked", "unavailable", "conflict", "do-not-invite"}
_ID_KEYS = ("openalex_id", "openalex", "id")
_DATE_KEYS = ("last_invited", "last invited", "last_invited_date", "date")


def _norm_name(s):
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def _norm_orcid(s):
    return (s or "").strip().rstrip("/").split("/")[-1]


def load(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(f)]


def _first(row, keys):
    for k in keys:
        if row.get(k):
            return row[k]
    return ""


def _is_excluded(row, cooldown_months, as_of):
    status = (row.get("status") or "").lower()
    if status in PERMANENT:
        return True
    last = _first(row, _DATE_KEYS)
    if not last:
        return True
    try:
        parts = [int(x) for x in re.split(r"[-/]", last)[:2]]
        y = parts[0]
        m = parts[1] if len(parts) > 1 else 1
        months = (as_of.year - y) * 12 + (as_of.month - m)
        return months < cooldown_months
    except (ValueError, IndexError):
        return True


def active_exclusions(path, cooldown_months=12, as_of=None):
    """Return (ids, orcids, names) currently in effect, plus the count of active rows."""
    as_of = as_of or date.today()
    ids, orcids, names, n = set(), set(), set(), 0
    for row in load(path):
        if not _is_excluded(row, cooldown_months, as_of):
            continue
        n += 1
        if _first(row, _ID_KEYS):
            ids.add(_first(row, _ID_KEYS).split("/")[-1])
        if row.get("orcid"):
            orcids.add(_norm_orcid(row["orcid"]))
        if row.get("name"):
            names.add(_norm_name(row["name"]))
    return {"ids": ids, "orcids": orcids, "names": names, "n_active": n}


def matches(cand, excl):
    if cand.id in excl["ids"]:
        return True
    if cand.orcid and _norm_orcid(cand.orcid) in excl["orcids"]:
        return True
    return _norm_name(cand.name) in excl["names"]
