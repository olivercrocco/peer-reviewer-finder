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
    seniority = 1.5 if wc >= 15 else (1.0 if wc >= 6 else (0.5 if wc >= 3 else 0.0))

    total = (core_c + sec_c + method_c + ctx_c
             - 0.5 * overflow
             + 1.0 * len(breadth["core"])
             + recency_bonus + seniority)

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


def career_stage(prof, current_year=2026):
    """Coarse career-stage proxy from h-index + output (no extra API calls).
    Returns 'senior' | 'mid-career' | 'early-career'. Heuristic, not authoritative."""
    h = (prof or {}).get("h_index") or 0
    wc = (prof or {}).get("works_count") or 0
    if h >= 25 or wc >= 100:
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
