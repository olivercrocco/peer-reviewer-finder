"""Term search across the journal pool, with a precision gate.

OpenAlex `search` is recall-friendly (it spans title/abstract/fulltext and ranks
by relevance), which is great for finding candidates but pulls in works that only
mention a term in passing. The precision gate re-checks each returned work and
keeps a term's credit only if the term actually appears in the TITLE or ABSTRACT.
This is what stops the field's prolific generalists from matching every term
loosely and burying the real subject-matter experts.
"""

import re

STOPWORDS = {"and", "the", "of", "for", "with", "in", "on", "to", "a", "an",
             "or", "by", "as", "at", "is", "are"}


def abstract_text(inv):
    """Reconstruct plain abstract text from OpenAlex' abstract_inverted_index."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def match_strength(term, title, abstract):
    """How strongly does `term` actually appear in the title/abstract?
        2.0  exact phrase in title
        1.0  exact phrase in abstract
        0.5  all content tokens present somewhere in title+abstract
        0.0  not really there (relevance/fulltext-only -> discarded by caller)
    """
    t = (title or "").lower()
    a = (abstract or "").lower()
    term_l = term.lower()
    if term_l in t:
        return 2.0
    if term_l in a:
        return 1.0
    tokens = [tok for tok in re.split(r"\W+", term_l)
              if len(tok) > 2 and tok not in STOPWORDS]
    blob = t + " " + a
    if tokens and all(tok in blob for tok in tokens):
        return 0.5
    return 0.0


def search_term(client, source_filter, term, per_query=80, min_strength=0.5):
    """Search the journal pool for `term`; return only works that genuinely
    match (title/abstract). Each item: dict with work meta + this term's strength.
    """
    data = client.get("works", {
        "search": term,
        "filter": f"primary_location.source.id:{source_filter},is_paratext:false",
        "per-page": per_query,
        "sort": "relevance_score:desc",
        "select": "id,title,publication_year,primary_location,authorships,"
                  "abstract_inverted_index,type,cited_by_count",
    })
    out = []
    for w in data.get("results", []):
        title = w.get("title") or ""
        strength = match_strength(term, title, abstract_text(w.get("abstract_inverted_index")))
        if strength < min_strength:
            continue
        out.append({"work": w, "strength": strength})
    return out, len(data.get("results", []))


def find_submission(client, title):
    """Best-effort: locate the submission in OpenAlex (to exclude self-matches).
    Requires strong title-token overlap. Returns dict or None."""
    data = client.get("works", {"search": title, "per-page": 3,
                                 "select": "id,title,publication_year,authorships"})
    qt = set(re.split(r"\W+", title.lower()))
    for w in data.get("results", []):
        wt = set(re.split(r"\W+", (w.get("title") or "").lower()))
        if len(qt & wt) / max(len(qt), 1) > 0.6:
            return {
                "id": w["id"], "title": w.get("title"),
                "year": w.get("publication_year"),
                "authors": [(au["author"]["id"].split("/")[-1],
                             au["author"]["display_name"])
                            for au in w.get("authorships", [])],
            }
    return None
