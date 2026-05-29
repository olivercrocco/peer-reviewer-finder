"""Orchestration: search -> aggregate -> enrich -> score -> COI -> diversify."""

import time

from . import coi, ledger, search
from .config import select_sources
from .score import classify, prelim_value, score

TIERS = ("core", "secondary", "method_primary", "method_generic", "context")


class Candidate:
    __slots__ = ("id", "name", "orcid", "works", "prof")

    def __init__(self, aid):
        self.id = aid
        self.name = ""
        self.orcid = ""
        self.works = {}        # work_id -> work info dict
        self.prof = {}

    def work(self, wid):
        return self.works.setdefault(wid, {
            "title": "", "year": None, "journal": "", "discipline": "",
            "lead": False, "terms": {}, "inst_id": "", "inst_name": "", "country": ""})


def _fold(matches, term, bucket, id_meta, candidates):
    """Fold one term's matched works into the candidate map."""
    for m in matches:
        w = m["work"]
        strength = m["strength"]
        wid = w["id"].split("/")[-1]
        src = (w.get("primary_location") or {}).get("source") or {}
        sid = (src.get("id") or "").split("/")[-1]
        meta = id_meta.get(sid, {})
        auths = w.get("authorships", [])
        n = len(auths)
        for idx, a in enumerate(auths):
            au = a.get("author") or {}
            aid = (au.get("id") or "").split("/")[-1]
            if not aid:
                continue
            c = candidates[aid]
            c.name = au.get("display_name") or c.name
            c.orcid = au.get("orcid") or c.orcid
            wi = c.work(wid)
            wi["title"] = w.get("title") or ""
            wi["year"] = w.get("publication_year")
            wi["journal"] = meta.get("name") or src.get("display_name") or ""
            wi["discipline"] = (meta.get("disciplines") or [""])[0]
            wi["lead"] = wi["lead"] or (idx == 0 or idx == n - 1)
            insts = a.get("institutions") or []
            if insts:
                wi["inst_id"] = (insts[0].get("id") or "").split("/")[-1]
                wi["inst_name"] = insts[0].get("display_name") or wi["inst_name"]
                wi["country"] = insts[0].get("country_code") or wi["country"]
            prev = wi["terms"].get(term)
            if not prev or strength > prev["strength"]:
                wi["terms"][term] = {"strength": strength, "bucket": bucket}


def run(spec, client, registry, *, top=25, panel_size=None, per_query=100,
        enrich_top=150, current_year=2026, confidential=True,
        ledger_path=None, ledger_cooldown=12, ledger_as_of=None, log=print):
    # 1. terms by tier
    query_bucket = {}
    for tier in TIERS:
        for t in spec.get(f"{tier}_terms", []):
            query_bucket[t] = tier
    if not query_bucket:
        raise ValueError("Article spec has no search terms in any tier.")

    # 2. journal pool
    disciplines = spec.get("disciplines")          # None => all
    source_ids, id_meta = select_sources(
        registry, disciplines=disciplines, journals=spec.get("journals"))
    if not source_ids:
        raise ValueError("No journals selected from the registry.")
    source_filter = "|".join(source_ids)
    log(f"Pool: {len(source_ids)} journals"
        + (f" across {len(disciplines)} disciplines" if disciplines else " (all disciplines)")
        + f"; {len(query_bucket)} terms")

    # 3. search + aggregate (auto-vivifying map of author id -> Candidate)
    class _Candidates(dict):
        def __missing__(self, k):
            self[k] = Candidate(k)
            return self[k]
    candidates = _Candidates()

    for term, bucket in query_bucket.items():
        matches, returned = search.search_term(client, source_filter, term, per_query)
        _fold(matches, term, bucket, id_meta, candidates)
        log(f"  [{bucket:14}] kept {len(matches):>3}/{returned:<3}  <- {term}")
        time.sleep(0.2)
    log(f"Candidate authors gathered: {len(candidates)}")

    # 4. conflicts: submission self-match + supplied author institutions + manual
    excl_ids = set(spec.get("exclude_author_ids", []))
    excl_names = {n.lower() for n in spec.get("exclude_author_names", [])}
    if confidential:
        log("\U0001F512 Confidential mode ON: only generic topic terms are sent to "
            "OpenAlex. Title, abstract, your email, and author-institution names are "
            "NOT transmitted; no AI/LLM processes the manuscript. "
            "(Supply exclude_author_names to drop the submitting authors.)")
        found = None
    else:
        found = search.find_submission(client, spec["title"])
        if found:
            for aid, nm in found["authors"]:
                excl_ids.add(aid)
                excl_names.add(nm.lower())
    author_inst_ids, author_tokens = coi.resolve_author_institutions(
        client, spec.get("author_institutions", []), resolve_ids=not confidential)

    # ORCID-based co-author COI (no names). Excludes the authors themselves + their
    # recent collaborators. Opt-in in confidential mode because it transmits the ORCIDs.
    orcids = spec.get("author_orcids", [])
    screen = spec.get("screen_coauthors")
    do_screen = screen if screen is not None else (bool(orcids) and not confidential)
    coauthor_coi = {"screened": False, "n_authors": 0, "n_coauthors": 0}
    if orcids and do_screen:
        a_ids, co_ids = coi.resolve_coauthors(client, orcids, since_year=current_year - 5)
        excl_ids |= a_ids | co_ids
        coauthor_coi = {"screened": True, "n_authors": len(a_ids), "n_coauthors": len(co_ids)}
        log(f"Co-author COI (via ORCID): excluded {len(a_ids)} author(s) + "
            f"{len(co_ids)} recent collaborators.")
    elif orcids and confidential and not screen:
        log("Author ORCIDs provided but co-author screening is OFF in confidential mode "
            "(set screen_coauthors=true / --screen-coauthors to enable — it transmits ORCIDs).")

    # reviewer over-use ledger (local + confidential): drop recently-invited / ineligible
    ledger_excl = None
    if ledger_path:
        ledger_excl = ledger.active_exclusions(ledger_path, ledger_cooldown, ledger_as_of)
        log(f"Over-use ledger: {ledger_excl['n_active']} active exclusion(s) from {ledger_path}.")

    # 5. enrich only the most promising candidates (scalability)
    ranked_pre = sorted(candidates.values(), key=prelim_value, reverse=True)
    to_enrich = [c.id for c in ranked_pre[:enrich_top]]
    prof = client.fetch_authors(to_enrich)
    for aid, p in prof.items():
        candidates[aid].prof = p

    # 6. score + filter
    rows = []
    same_inst_blocked = ledger_blocked = 0
    for c in ranked_pre[:enrich_top]:
        if c.id in excl_ids or c.name.lower() in excl_names:
            continue
        if ledger_excl and ledger.matches(c, ledger_excl):
            ledger_blocked += 1
            continue
        sc = score(c, current_year=current_year)
        if (sc["core_breadth"] + sc["secondary_breadth"]
                + sc["method_primary_breadth"] + sc["method_generic_breadth"]) == 0:
            continue
        if coi.same_institution(c, author_inst_ids, author_tokens):
            same_inst_blocked += 1
            continue
        rows.append((c, sc, classify(sc)))
    rows.sort(key=lambda r: r[1]["score"], reverse=True)
    if author_inst_ids or author_tokens:
        log(f"Same-institution COI removed {same_inst_blocked} candidate(s).")
    if ledger_blocked:
        log(f"Over-use ledger removed {ledger_blocked} candidate(s).")

    # 7. co-author graph + scorecard-driven diversified panel
    from .config import PANEL_DEFAULTS
    from .diversify import select_panel
    reqs = {**PANEL_DEFAULTS, **(spec.get("panel") or {})}
    if panel_size:
        reqs["size"] = panel_size
    graph = coi.coauthor_graph([r[0] for r in rows])
    panel, scorecard = select_panel(
        rows[:max(60, reqs["size"] * 8)], graph, reqs, current_year=current_year)
    # the scorecard CHOOSES a diverse, covered set; display it ordered by best fit
    panel.sort(key=lambda t: t[1]["score"], reverse=True)

    return {
        "spec": spec, "rows": rows[:top], "all_rows": rows, "panel": panel,
        "scorecard": scorecard, "panel_reqs": reqs,
        "found": found, "coauthors": graph, "confidential": confidential,
        "current_year": current_year, "coauthor_coi": coauthor_coi,
        "author_inst_ids": author_inst_ids,
        "n_candidates": len(candidates), "n_journals": len(source_ids),
        "same_inst_blocked": same_inst_blocked,
        "ledger_blocked": ledger_blocked,
        "ledger_path": str(ledger_path) if ledger_path else None,
    }
