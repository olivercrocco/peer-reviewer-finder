"""Configuration: the journal registry and scoring defaults.

The journal registry (`journals.yaml`) is the heart of the pool. It is a list of
journals, each tagged with the discipline(s) it belongs to, so a run can include
or exclude whole disciplines. Edit it freely; resolve new journals' OpenAlex ids
with `python -m reviewer_id.add_journal` or by hand from
https://api.openalex.org/sources/issn:XXXX-XXXX .
"""

import json
from pathlib import Path

from .score import TIER_WEIGHT  # noqa: F401  (re-exported as the default weights)

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "journals.yaml"
# Reviewer over-use ledger: auto-used if this file exists (git-ignored, local-only).
LEDGER_PATH = REPO_ROOT / "reviewer-ledger.csv"

# Default "scorecard" the suggested panel tries to satisfy. Override per-manuscript
# via the spec's "panel" block. These are opinions, not hard rules — if a box can't
# be filled from the pool, the report says so rather than failing.
# Size defaults to 9: reviewer-invitation response rates are low and some candidates
# may be over-invited / ineligible, so the editor needs a deeper bench in reserve.
PANEL_DEFAULTS = {
    "size": 9,
    "max_per_institution": 1,   # independence: at most N reviewers per institution
    "min_countries": 4,         # geographic spread
    "min_disciplines": 2,       # disciplinary spread (uses the cross-discipline pool)
    "min_method_experts": 1,    # expertise in the manuscript's method(s)
    "min_early_career": 1,      # cultivate early-career reviewers
    "min_senior": 1,            # at least one senior anchor
}

# Used only if journals.yaml is missing, so the package is runnable out of the box.
FALLBACK_REGISTRY = [
    {"openalex_id": "S191693275", "name": "Human Resource Development Quarterly",
     "issn": ["1044-8004", "1532-1096"], "disciplines": ["Human Resource Development"], "tier": "flagship"},
    {"openalex_id": "S140059072", "name": "Human Resource Development International",
     "issn": ["1367-8868", "1469-8374"], "disciplines": ["Human Resource Development"], "tier": "flagship"},
    {"openalex_id": "S49321836", "name": "Advances in Developing Human Resources",
     "issn": ["1523-4223", "1552-3055"], "disciplines": ["Human Resource Development"], "tier": "flagship"},
    {"openalex_id": "S37660120", "name": "Human Resource Development Review",
     "issn": ["1534-4843", "1552-6712"], "disciplines": ["Human Resource Development"], "tier": "flagship"},
]


def load_registry(path=REGISTRY_PATH):
    """Load the journal registry from YAML (preferred) or JSON. Falls back to the
    built-in HRD-only set if no file is found."""
    path = Path(path)
    if not path.exists():
        alt = path.with_suffix(".json")
        if alt.exists():
            return json.loads(alt.read_text())
        return list(FALLBACK_REGISTRY)
    text = path.read_text()
    try:
        import yaml
        data = yaml.safe_load(text)
    except ImportError:
        # journals.yaml is intentionally JSON-compatible YAML, so json can read it
        data = json.loads(text)
    return data.get("journals", data) if isinstance(data, dict) else data


def select_sources(registry, disciplines=None, tiers=None, journals=None):
    """Return (source_id_list, id_to_meta) for the requested slice of the registry.

    disciplines / tiers / journals (names or ids) are optional filters; omit for all.
    """
    disc = set(disciplines) if disciplines else None
    tset = set(tiers) if tiers else None
    jset = set(journals) if journals else None
    ids, meta = [], {}
    for j in registry:
        jid = j.get("openalex_id")
        if not jid:
            continue
        if disc and not (set(j.get("disciplines", [])) & disc):
            continue
        if tset and j.get("tier") not in tset:
            continue
        if jset and not (jid in jset or j.get("name") in jset):
            continue
        ids.append(jid)
        meta[jid] = {"name": j.get("name"),
                     "disciplines": j.get("disciplines", []),
                     "tier": j.get("tier")}
    return ids, meta


def all_disciplines(registry):
    out = []
    for j in registry:
        for d in j.get("disciplines", []):
            if d not in out:
                out.append(d)
    return out
