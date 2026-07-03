"""Scorecard-driven panel selection.

A good panel is a set of *boxes to check*, not just the top-N by score. From the
relevance-ranked candidates this greedily builds a panel that tries to satisfy a
configurable scorecard — institution spread, country spread, discipline spread,
method-expertise coverage, and a senior/early-career mix — while never pairing two
people who co-authored a matched work. Each requirement adds a bonus *only while it
is unmet*, so the selector fills gaps first, then takes the best remaining
candidates. If a box can't be filled from the pool, it's reported, not hidden.
"""

from collections import defaultdict

from .coi import current_country, disciplines_of, institution_key
from .score import career_stage, is_method_expert, is_primary_method_expert

W_REQ = 12.0    # bonus for a candidate that fills a still-unmet required box
W_SOFT = 2.0    # small standing bonus for added diversity


def select_panel(ranked, coauthors, reqs, current_year=2026):
    """`ranked`: list of (cand, sc, kind), best-first. `coauthors`: id -> {ids}.
    `reqs`: panel scorecard (see config.PANEL_DEFAULTS).
    Returns (chosen, scorecard) where chosen items are (cand, sc, kind, why)."""
    size = reqs["size"]
    maxinst = reqs["max_per_institution"]
    min_c, min_d = reqs["min_countries"], reqs["min_disciplines"]
    min_m, min_e, min_s = (reqs["min_method_experts"],
                           reqs["min_early_career"], reqs["min_senior"])
    min_mid = reqs.get("min_mid_career", 0)
    max_s = reqs.get("max_senior")            # None => no cap on senior scholars

    items = [{
        "cand": c, "sc": sc, "kind": kind,
        "inst": institution_key(c), "country": current_country(c),
        "discs": set(disciplines_of(c)),
        "method": is_method_expert(sc), "primary_method": is_primary_method_expert(sc),
        "stage": career_stage(c.prof, current_year),
    } for c, sc, kind in ranked]

    chosen = []
    inst_counts = defaultdict(int)
    countries, disciplines, picked_ids = set(), set(), set()
    n_method = n_early = n_mid = n_senior = 0

    while len(chosen) < size and items:
        best, best_val, best_idx = None, None, None
        for idx, it in enumerate(items):
            if inst_counts.get(it["inst"], 0) >= maxinst:
                continue
            if picked_ids & coauthors.get(it["cand"].id, set()):
                continue
            # hard cap on senior scholars so they can't fill the deeper bench
            if max_s is not None and it["stage"] == "senior" and n_senior >= max_s:
                continue
            val = it["sc"]["score"]
            new_country = bool(it["country"]) and it["country"] not in countries
            new_discs = it["discs"] - disciplines
            if it["method"] and n_method < min_m:
                val += W_REQ + (W_REQ * 0.4 if it["primary_method"] else 0.0)
            if it["stage"] == "early-career" and n_early < min_e:
                val += W_REQ
            if it["stage"] == "mid-career" and n_mid < min_mid:
                val += W_REQ
            if it["stage"] == "senior" and n_senior < min_s:
                val += W_REQ
            if new_country and len(countries) < min_c:
                val += W_REQ * 0.8
            if new_discs and len(disciplines) < min_d:
                val += W_REQ * 0.8
            if new_country:
                val += W_SOFT
            if new_discs:
                val += W_SOFT * 0.5
            if best_val is None or val > best_val:
                best, best_val, best_idx = it, val, idx
        if best is None:
            break
        it = best
        why = []
        if it["method"] and n_method < min_m:
            why.append("method" + (" (primary)" if it["primary_method"] else ""))
        if it["stage"] == "early-career" and n_early < min_e:
            why.append("early-career")
        if it["stage"] == "mid-career" and n_mid < min_mid:
            why.append("mid-career")
        if it["stage"] == "senior" and n_senior < min_s:
            why.append("senior anchor")
        if it["country"] and it["country"] not in countries:
            why.append(f"+{it['country']}")
        nd = it["discs"] - disciplines
        if nd:
            why.append("+" + sorted(nd)[0])
        chosen.append((it["cand"], it["sc"], it["kind"], ", ".join(why) or "high relevance"))
        inst_counts[it["inst"]] += 1
        if it["country"]:
            countries.add(it["country"])
        disciplines |= it["discs"]
        picked_ids.add(it["cand"].id)
        n_method += int(it["method"])
        n_early += int(it["stage"] == "early-career")
        n_mid += int(it["stage"] == "mid-career")
        n_senior += int(it["stage"] == "senior")
        items.pop(best_idx)

    scorecard = {
        "size": (len(chosen), size),
        "institutions": (len([k for k, v in inst_counts.items() if v]), None),
        "countries": (len(countries), min_c),
        "disciplines": (len(disciplines), min_d),
        "method_experts": (n_method, min_m),
        "early_career": (n_early, min_e),
        "mid_career": (n_mid, min_mid),
        "senior": (n_senior, min_s),
    }
    return chosen, scorecard
