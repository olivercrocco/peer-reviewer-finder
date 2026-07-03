"""Tier-weighted, precision-gated relevance scoring.

Search terms are tiered by how *distinctive* they are to the manuscript, because
broad terms (e.g. "social justice", "leadership") match the field's most prolific
authors and would otherwise dominate. A real match on a distinctive `core` term
counts far more than a match on a generic one.

    core            the paper's defining subject
    secondary       related constructs it touches
    method_primary  its actual methodology (e.g. bibliometrics, topic modeling)
    method_generic  common methods that are weak discriminators (e.g. lit review)
    context         setting (e.g. higher education)
"""

from collections import defaultdict

TIER_WEIGHT = {
    "core": 3.0,
    "secondary": 1.0,
    "method_primary": 2.0,
    "method_generic": 0.8,
    "context": 0.4,
}

MAX_WORKS_SCORED = 8        # cap evidence per author so volume can't dominate


def _work_has_real_core(work):
    return any(info["bucket"] == "core" and info["strength"] >= 1.0
              for info in work["terms"].values())


def score(cand, weights=TIER_WEIGHT, current_year=2026):
    """Return a dict of the candidate's score and its components."""
    credit = defaultdict(float)
    breadth = defaultdict(set)
    n = defaultdict(int)
    years, core_lead, contribs = [], 0, []

    for w in cand.works.values():
        pos = 1.0 if w["lead"] else 0.6
        work_best, real = 0.0, False
        for term, info in w["terms"].items():
            s, b = info["strength"], info["bucket"]
            c = weights[b] * s * pos
            credit[b] += c
            n[b] += 1
            work_best = max(work_best, c)
            if s >= 1.0:                      # exact phrase actually present
                breadth[b].add(term)
                real = True
        if real and w["year"]:
            years.append(w["year"])
        if w["lead"] and _work_has_real_core(w):
            core_lead += 1
        contribs.append(work_best)

    contribs.sort(reverse=True)
    overflow = sum(contribs[MAX_WORKS_SCORED:])         # weak long tail

    core_c = credit["core"]
    sec_c = credit["secondary"]
    method_c = credit["method_primary"] + credit["method_generic"]
    ctx_c = credit["context"]

    recency = max(years) if years else None
    recency_bonus = 2 if (recency and recency >= current_year - 3) else (
        1 if (recency and recency >= current_year - 6) else 0)
    wc = (cand.prof or {}).get("works_count") or 0
    # A small, FLAT credibility floor: it distinguishes an established scholar from a
    # one-off author but does not escalate with output. Raw productivity is a
    # seniority proxy, and the old escalating bonus (up to +1.5 for >=15 works) put a
    # thumb on the scale for senior scholars. Fit, not volume, should rank a reviewer.
    track_record = 0.6 if wc >= 5 else (0.3 if wc >= 2 else 0.0)

    total = (core_c + sec_c + method_c + ctx_c
             - 0.5 * overflow
             + 1.0 * len(breadth["core"])
             + recency_bonus + track_record)

    return {
        "score": round(total, 2),
        "core_credit": round(core_c, 2),
        "secondary_credit": round(sec_c, 2),
        "method_credit": round(method_c, 2),
        "core_breadth": len(breadth["core"]),
        "secondary_breadth": len(breadth["secondary"]),
        "method_primary_breadth": len(breadth["method_primary"]),
        "method_generic_breadth": len(breadth["method_generic"]),
        "n_core_works": n["core"],
        "n_method_works": n["method_primary"] + n["method_generic"],
        "core_lead_works": core_lead,
        "recency": recency,
    }


def classify(sc):
    core = sc["core_credit"] > 0
    method = sc["method_credit"] > 0
    if core and method:
        return "Topic + Method"
    if core:
        return "Topic"
    if sc["method_primary_breadth"] > 0:
        return "Method (primary)"
    if method:
        return "Method (review)"
    return "Adjacent"


def academic_age(prof, current_year=2026):
    """Years since the author's first recorded publication, from OpenAlex
    `counts_by_year` (no extra API call). Returns None if there's no year data.

    counts_by_year reaches back ~20 years, deep enough to place early- and
    mid-career scholars precisely; for long careers it saturates near the window
    edge, which still reads as 'senior' and is fine for this purpose.
    """
    cby = (prof or {}).get("counts_by_year") or []
    years = [c.get("year") for c in cby
             if c.get("year") and (c.get("works_count") or 0) > 0]
    return max(0, current_year - min(years)) if years else None


def career_stage(prof, current_year=2026):
    """Career-stage proxy. PRIMARY axis is academic age (years since first
    publication); h-index only refines the edges. Career stage means time in the
    field, not lifetime output — keying off productivity alone (the old rule)
    mislabels prolific-but-recent scholars 'senior' and rarely finds early-career
    reviewers. Returns 'senior' | 'mid-career' | 'early-career'. Heuristic.
    """
    p = prof or {}
    h = p.get("h_index") or 0
    wc = p.get("works_count") or 0
    age = academic_age(p, current_year)

    if age is not None:
        if age <= 7 and h < 20:              # first ~7 years, absent an unusual h-index
            return "early-career"
        # Senior means a long career AND an established citation record (or a standout
        # record regardless of years). Age alone isn't enough: a first publication 16+
        # years ago is often a doctoral paper, and a modest h-index at that age reads as
        # steady mid-career, not senior. Gating on h also keeps the senior count from
        # re-inflating, which is the whole point of the rebalance.
        if (age >= 16 and h >= 20) or h >= 40:
            return "senior"
        return "mid-career"

    # No year data: fall back to a productivity-only heuristic, but less eager to
    # call someone senior than the original thresholds were.
    if h >= 30 or wc >= 120:
        return "senior"
    if h <= 10 and wc <= 30:
        return "early-career"
    return "mid-career"


def recent_works(prof, current_year=2026, window=3):
    cby = (prof or {}).get("counts_by_year") or []
    return sum(c.get("works_count", 0) for c in cby
               if c.get("year", 0) >= current_year - window + 1)


def is_active(prof, current_year=2026, window=3):
    """Has the candidate published recently? A weak responsiveness/"not retired" signal."""
    return recent_works(prof, current_year, window) > 0


def is_method_expert(sc):
    return sc.get("method_credit", 0) > 0 and (
        sc.get("method_primary_breadth", 0) + sc.get("method_generic_breadth", 0)) >= 1


def is_primary_method_expert(sc):
    return sc.get("method_primary_breadth", 0) >= 1


def prelim_value(cand):
    """Cheap pre-enrichment relevance, used to pick which candidates to enrich."""
    v = 0.0
    for w in cand.works.values():
        pos = 1.0 if w["lead"] else 0.6
        for info in w["terms"].values():
            v += TIER_WEIGHT[info["bucket"]] * info["strength"] * pos
    return v
