"""Conflict-of-interest screening.

Two checks:
  * same institution as a submitting author  (primary: OpenAlex institution id;
    fallback: normalized name match)
  * co-authorship between recommended reviewers (so the suggested panel members
    are independent of one another) — inferred from shared works in the matched pool
"""

import re

_INST_STOP = {"university", "univ", "of", "the", "college", "school", "institute",
              "for", "and", "at", "de", "la", "el", "center", "centre", "department"}


def normalize_inst(name):
    """Token set of an institution name, minus boilerplate words, for fuzzy match."""
    toks = [t for t in re.split(r"\W+", (name or "").lower())
            if t and t not in _INST_STOP and len(t) > 1]
    return frozenset(toks)


def resolve_author_institutions(client, names, resolve_ids=True):
    """Resolve submitting-author institution strings to OpenAlex ids + name tokens.
    Returns (set_of_ids, list_of_token_sets).

    With resolve_ids=False (confidential mode) the institution names are NOT sent
    to OpenAlex; matching falls back to local name-token comparison only. Supply
    full institution names for best local matching in that mode.
    """
    ids, token_sets = set(), []
    for nm in names or []:
        token_sets.append(normalize_inst(nm))
        if resolve_ids:
            inst = client.resolve_institution(nm)
            if inst and inst.get("id"):
                ids.add(inst["id"])
                token_sets.append(normalize_inst(inst.get("display_name")))
    return ids, [ts for ts in token_sets if ts]


def candidate_institutions(cand):
    """All (id, name, country) an institution-affiliation a candidate shows across
    matched works plus their OpenAlex last-known institution."""
    seen = {}
    for w in cand.works.values():
        if w.get("inst_id") or w.get("inst_name"):
            seen[w.get("inst_id") or w.get("inst_name")] = (
                w.get("inst_id", ""), w.get("inst_name", ""), w.get("country", ""))
    p = cand.prof or {}
    if p.get("last_inst_id") or p.get("last_inst"):
        seen.setdefault(p.get("last_inst_id") or p.get("last_inst"),
                        (p.get("last_inst_id", ""), p.get("last_inst", ""),
                         p.get("last_country", "")))
    return list(seen.values())


def same_institution(cand, author_inst_ids, author_token_sets, jaccard=0.6):
    """True if any of the candidate's institutions matches a submitting author's."""
    for inst_id, inst_name, _ in candidate_institutions(cand):
        if inst_id and inst_id in author_inst_ids:
            return True
        cset = normalize_inst(inst_name)
        if not cset:
            continue
        for aset in author_token_sets:
            if not aset:
                continue
            if cset == aset or cset <= aset or aset <= cset:
                return True
            inter = len(cset & aset)
            union = len(cset | aset)
            if union and inter / union >= jaccard:
                return True
    return False


def current_affiliation(cand):
    """Most-recent matched-work institution beats OpenAlex' (often stale) last
    known institution. Returns (name, country)."""
    dated = [w for w in cand.works.values() if w.get("inst_name") and w.get("year")]
    if dated:
        w = max(dated, key=lambda w: w["year"])
        return w["inst_name"], (w.get("country") or "")
    p = cand.prof or {}
    if p.get("last_inst"):
        return p["last_inst"], p.get("last_country") or ""
    return "", ""


def current_country(cand):
    return current_affiliation(cand)[1]


def institution_key(cand):
    """A stable key for 'same institution' grouping — prefer OpenAlex ids."""
    dated = [w for w in cand.works.values() if w.get("inst_id") and w.get("year")]
    if dated:
        return max(dated, key=lambda w: w["year"])["inst_id"]
    p = cand.prof or {}
    if p.get("last_inst_id"):
        return p["last_inst_id"]
    if p.get("last_inst"):
        return p["last_inst"]
    for w in cand.works.values():
        if w.get("inst_id"):
            return w["inst_id"]
        if w.get("inst_name"):
            return w["inst_name"]
    return cand.id


def disciplines_of(cand):
    """Distinct disciplines (from the journal registry) where the candidate matched."""
    out = []
    for w in cand.works.values():
        d = w.get("discipline")
        if d and d not in out:
            out.append(d)
    return out


_ORCID_RE = re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")


def _valid_orcid(s):
    """Return the bare ORCID id if `s` is a valid ORCID (bare or orcid.org URL),
    else None — so a malformed/hostile value isn't interpolated into a query."""
    m = _ORCID_RE.match((s or "").strip())
    return m.group(1) if m else None


def resolve_coauthors(client, orcids, since_year=None, max_works=200):
    """Given submitting-author ORCID iDs (NOT names), return
    (author_openalex_ids, recent_coauthor_ids) so both the authors themselves and
    their recent collaborators can be excluded. NOTE: this transmits the ORCIDs to
    OpenAlex (not the manuscript) — it is opt-in in confidential mode."""
    author_ids, coauthor_ids = set(), set()
    for orcid in orcids or []:
        oid = _valid_orcid(orcid)
        if not oid:
            continue   # skip a malformed ORCID rather than shaping a request from it
        a = client.get(f"authors/orcid:{oid}")
        aid = (a.get("id") or "").split("/")[-1]
        if not aid:
            continue
        author_ids.add(aid)
        data = client.get("works", {
            "filter": f"author.id:{aid}", "per-page": min(max_works, 200),
            "sort": "publication_date:desc",
            "select": "authorships,publication_year"})
        for w in data.get("results", []):
            if since_year and (w.get("publication_year") or 0) < since_year:
                continue
            for au in w.get("authorships", []):
                cid = (au.get("author", {}).get("id") or "").split("/")[-1]
                if cid:
                    coauthor_ids.add(cid)
    coauthor_ids -= author_ids
    return author_ids, coauthor_ids


def coauthor_graph(candidates):
    """Map candidate_id -> set of candidate_ids that share a matched work.
    `candidates` is an iterable of objects with .id and .works (dict keyed by work id)."""
    work_to_authors = {}
    for c in candidates:
        for wid in c.works:
            work_to_authors.setdefault(wid, set()).add(c.id)
    graph = {c.id: set() for c in candidates}
    for authors in work_to_authors.values():
        if len(authors) > 1:
            for a in authors:
                graph[a] |= (authors - {a})
    return graph
