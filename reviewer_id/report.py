"""Write the reviewer outputs: a suggested panel, a ranked report, a CSV, and a
raw evidence dump. The panel is the editor-facing deliverable; everything else is
there so the editor can pick alternates and audit the matches.
"""

import csv
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

from .coi import current_affiliation, disciplines_of
from .score import career_stage, is_active


def _disciplines_matched(cand):
    return disciplines_of(cand)


def _contact_record(cand, result):
    """Build a paste-ready contact record for a reviewer, merging what we already
    know (OpenAlex affiliation, ORCID iD) with any public ORCID enrichment, and
    always providing ready-made lookup URLs for whatever's still missing.

    Nothing here transmits anything: the ORCID data was fetched earlier (only if
    --contacts was set); the search URLs are just strings the editor can click.
    """
    aff_oa, ctry_oa = current_affiliation(cand)
    c = (result.get("contacts") or {}).get(cand.id) or {}

    email = c.get("email") or ""
    # ORCID's current employer is usually fresher than OpenAlex's last-known one.
    affiliation = c.get("affiliation") or aff_oa or ""
    aff_source = "ORCID" if c.get("affiliation") else ("OpenAlex" if aff_oa else "")
    country = c.get("country") or ctry_oa or ""
    role = c.get("role") or ""

    orcid_bare = c.get("orcid") or ((cand.orcid or "").rstrip("/").split("/")[-1] if cand.orcid else "")
    orcid_url = f"https://orcid.org/{orcid_bare}" if orcid_bare else ""
    openalex_url = f"https://openalex.org/{cand.id}"

    name = cand.name or ""
    q = f'"{name}" {affiliation} email'.strip()
    google_url = f"https://www.google.com/search?q={quote_plus(q)}"
    scholar_url = f"https://scholar.google.com/scholar?q={quote_plus(name)}"

    return {
        "name": name, "email": email,
        "email_source": ("ORCID public" if email else ""),
        "affiliation": affiliation, "affiliation_source": aff_source,
        "role": role, "country": country,
        "orcid": orcid_url, "openalex": openalex_url,
        "google_search": google_url, "scholar_search": scholar_url,
    }


def _scorecard_line(result):
    sc = result.get("scorecard") or {}

    def fmt(key, label):
        v = sc.get(key)
        if not v:
            return None
        actual, target = v
        if target is None:
            return f"{label} {actual}"
        return f"{'✓' if actual >= target else '✗'} {label} {actual}/{target}"

    order = [("size", "size"), ("institutions", "institutions"),
             ("countries", "countries"), ("disciplines", "disciplines"),
             ("method_experts", "method experts"), ("early_career", "early-career"),
             ("mid_career", "mid-career"), ("senior", "senior")]
    parts = [fmt(k, l) for k, l in order]
    return " · ".join(p for p in parts if p), [
        l for k, l in order if (v := sc.get(k)) and v[1] is not None and v[0] < v[1]]


def _evidence(cand, limit=5):
    works = sorted(
        cand.works.values(),
        key=lambda w: (max((i["strength"] for i in w["terms"].values()), default=0),
                       w["year"] or 0), reverse=True)
    return works[:limit]


def _safe_slug(slug):
    """Sanitize a spec-supplied slug so output filenames can't escape outdir:
    drop any path components and reduce to [A-Za-z0-9._-]."""
    s = re.sub(r"[^A-Za-z0-9._-]", "_", Path(str(slug or "")).name).strip("._")
    return s or "output"


def write_all(result, outdir, slug):
    outdir = Path(outdir)
    slug = _safe_slug(slug)
    outdir.mkdir(parents=True, exist_ok=True)
    spec, rows, panel, found = (result["spec"], result["rows"],
                                result["panel"], result["found"])

    _write_panel(outdir / f"{slug}_panel.md", result)
    _write_report(outdir / f"{slug}_reviewers.md", result)
    _write_csv(outdir / f"{slug}_candidates.csv", result)
    _write_contacts(outdir / f"{slug}_contacts.csv", result)
    _write_raw(outdir / f"{slug}_raw.json", result)
    return {
        "panel": outdir / f"{slug}_panel.md",
        "report": outdir / f"{slug}_reviewers.md",
        "csv": outdir / f"{slug}_candidates.csv",
        "contacts": outdir / f"{slug}_contacts.csv",
        "raw": outdir / f"{slug}_raw.json",
    }


def _coi_block(result, md):
    spec = result["spec"]
    conf = result.get("confidential")
    if conf:
        md.append("- **Confidential mode:** the manuscript title, abstract, your email, and "
                  "author-institution names were **not** transmitted to OpenAlex — only generic "
                  "topic terms were searched, and no AI/LLM processed the manuscript.")
    if spec.get("author_institutions"):
        how = "local name match" if conf else "OpenAlex id + name match"
        md.append(f"- **Author institutions excluded** ({how}): "
                  f"{', '.join(spec['author_institutions'])} "
                  f"(removed {result['same_inst_blocked']} same-institution candidate(s)).")
    else:
        md.append("- **No author institutions supplied** — same-institution conflicts "
                  "were *not* screened. Add `author_institutions` to the spec to enable.")
    cc = result.get("coauthor_coi") or {}
    if cc.get("screened"):
        md.append(f"- **Submitting authors + recent collaborators excluded via ORCID** "
                  f"({cc['n_authors']} author(s) + {cc['n_coauthors']} co-authors removed) — "
                  f"no author names used.")
    if result.get("ledger_blocked"):
        md.append(f"- **Over-use ledger:** removed {result['ledger_blocked']} recently-invited / "
                  f"ineligible candidate(s) from your local list (nothing transmitted).")
    if conf:
        md.append("- **Submitting authors excluded by institution** (no author names used): "
                  "the title self-match lookup is disabled in confidential mode, so authors are "
                  "filtered via `author_institutions` — list *every* author institution to ensure "
                  "each is caught. Screen co-author / advisor conflicts manually.")
    elif result["found"]:
        md.append(f"- **Self-match excluded:** submission matched an OpenAlex record "
                  f"({result['found']['year']}); its authors were removed.")
    else:
        md.append("- **Submission not found in OpenAlex** (likely unpublished) — screen "
                  "co-author / advisor conflicts manually once the author list is known.")
    md.append("- **Panel members are mutually independent** (no shared co-authored work "
              "in the matched pool) and **from distinct institutions**.")


def _write_panel(path, result):
    spec = result["spec"]
    cy = result.get("current_year", 2026)
    line, unmet = _scorecard_line(result)
    md = [f"# Suggested reviewer panel\n",
          f"**Manuscript:** {spec['title']}\n",
          f"*Pool: {result['n_journals']} journals; {result['n_candidates']} candidate "
          f"authors matched. {len(result['panel'])} proposed, **ranked by best fit** but "
          f"selected to satisfy a diversity + expertise scorecard — a deeper bench given "
          f"low invitation response rates and reviewers who may be over-tapped. The editor "
          f"makes the final call; invite from the top and keep the rest in reserve.*\n",
          f"\n**Scorecard:** {line}\n"]
    if unmet:
        md.append(f"> ⚠️ Couldn't fully fill from the pool: **{', '.join(unmet)}**. "
                  f"Widen disciplines, raise `--top`, or relax the target in the spec's `panel` block.\n")
    md += ["\n## Recommended panel\n",
           "| # | Reviewer | Role | Stage | Institution | Country | Email | In panel because |",
           "|---|---|---|---|---|---|---|---|"]
    for i, (cand, sc, kind, why) in enumerate(panel := result["panel"], 1):
        rec = _contact_record(cand, result)
        stage = career_stage(cand.prof, cy)
        email_cell = rec["email"] or f"[look up]({rec['google_search']})"
        md.append(f"| {i} | **{cand.name}** | {kind} | {stage} | "
                  f"{rec['affiliation'] or '—'} | {rec['country'] or '—'} | {email_cell} | {why} |")
    md.append("\n*Details for each panel member:*\n")
    for i, (cand, sc, kind, why) in enumerate(panel, 1):
        rec = _contact_record(cand, result)
        aff, ctry = rec["affiliation"], rec["country"]
        stage = career_stage(cand.prof, cy)
        active = "" if is_active(cand.prof, cy) else "  ⚠ no publications in ~3 years"
        links = [f"[OpenAlex](https://openalex.org/{cand.id})"]
        if cand.orcid:
            links.append(f"[ORCID]({cand.orcid})")
        md.append(f"\n**{i}. {cand.name}** — {aff or '—'}{f' ({ctry})' if ctry else ''} · "
                  f"{kind} · {stage} · score {sc['score']} · " + " · ".join(links))
        if rec["email"]:
            contact = f"  - **Email:** {rec['email']} (public ORCID)"
            if rec["role"]:
                contact += f" · {rec['role']}"
            md.append(contact)
        else:
            md.append(f"  - **Email:** not public in ORCID — "
                      f"[Google]({rec['google_search']}) · [Scholar]({rec['scholar_search']})"
                      + (f" · {rec['role']}" if rec["role"] else ""))
        p = cand.prof or {}
        md.append(f"  - h-index {p.get('h_index','?')}, {p.get('works_count','?')} works"
                  f"{active}")
        disc = _disciplines_matched(cand)
        md.append(f"  - matched in: {', '.join(disc) or '—'}; "
                  f"core breadth {sc['core_breadth']} ({sc['core_lead_works']} as lead), "
                  f"method credit {sc['method_credit']}, most recent on-topic pub {sc['recency'] or '—'}")
        for w in _evidence(cand, 3):
            terms = ", ".join(w["terms"])
            md.append(f"  - *{w['title']}* — {w['journal']} {w['year']} [{terms}]")
    md.append("\n## Conflicts & independence\n")
    _coi_block(result, md)
    md.append("\n## Notes\n")
    awy = result.get("active_within_years")
    mra = result.get("max_related_paper_age")
    reqs_txt = []
    if mra:
        reqs_txt.append(f"a matching paper within the last {mra} years")
    if awy:
        reqs_txt.append(f"a publication within the last {awy} years")
    if reqs_txt:
        removed = []
        if result.get("related_age_blocked"):
            removed.append(f"{result['related_age_blocked']} whose on-topic work was all older")
        if result.get("stale_pub_blocked"):
            removed.append(f"{result['stale_pub_blocked']} with no recent publications")
        note = ("- **Freshness filters applied:** every candidate has "
                + " and ".join(reqs_txt) + ".")
        if removed:
            note += " Removed " + " and ".join(removed) + " before ranking."
        md.append(note)
    if result.get("contacts_enabled"):
        md.append("- **Emails** shown are the reviewer's own *public* ORCID email; most "
                  "researchers keep it private, so blanks are expected. For those, use the "
                  "ready-made search links here and in `*_contacts.csv`.")
    else:
        md.append("- **Emails** were not looked up (run with `--contacts` to pull public "
                  "ORCID emails + current employers). The `*_contacts.csv` sheet still lists "
                  "each reviewer with ready-made search links to find an address quickly.")
    md.append("- Verify each invitee's **current affiliation and email** before inviting; "
              "OpenAlex's last-known institution can lag and public emails may be dated.")
    md.append("- A paste-ready **`*_contacts.csv`** holds name, email, affiliation, country, "
              "ORCID/OpenAlex links, and search URLs for the Manuscript Central invite.")
    md.append("- Pick alternates from the full ranked list in the companion "
              "`*_reviewers.md` / `*_candidates.csv`.")
    Path(path).write_text("\n".join(md))


def _write_report(path, result):
    spec, rows, found = result["spec"], result["rows"], result["found"]
    panel_ids = {c.id for c, *_ in result["panel"]}
    md = [f"# Candidate reviewers — {spec['title']}\n",
          f"*Pool: {result['n_journals']} journals across the configured disciplines; "
          f"{result['n_candidates']} candidate authors matched on title/abstract. "
          f"Top {len(rows)} shown. ★ = in suggested panel.*\n", "\n---\n"]
    for i, (cand, sc, kind) in enumerate(rows, 1):
        aff, ctry = current_affiliation(cand)
        star = " ★" if cand.id in panel_ids else ""
        md.append(f"\n## {i}. {cand.name}{star}  ·  {kind}  ·  score {sc['score']}")
        md.append(f"**{aff or '—'}**" + (f" ({ctry})" if ctry else ""))
        p = cand.prof or {}
        md.append(f"OpenAlex works: {p.get('works_count','?')} · h-index: "
                  f"{p.get('h_index','?')} · most recent on-topic pub: {sc['recency'] or '—'}")
        links = [f"[OpenAlex](https://openalex.org/{cand.id})"]
        if cand.orcid:
            links.append(f"[ORCID]({cand.orcid})")
        md.append(" · ".join(links))
        if p.get("topics"):
            md.append(f"*Overall topics:* {', '.join(p['topics'])}")
        md.append(f"*Matched in:* {', '.join(_disciplines_matched(cand)) or '—'} · "
                  f"core breadth {sc['core_breadth']} ({sc['core_lead_works']} as lead) · "
                  f"method credit {sc['method_credit']}")
        md.append("\n*Representative matching papers:*")
        for w in _evidence(cand, 4):
            strong = max((i["strength"] for i in w["terms"].values()), default=0)
            tag = "★" if strong >= 2.0 else ("•" if strong >= 1.0 else "·")
            md.append(f"- {tag} *{w['title']}* — {w['journal']} {w['year']} "
                      f"[{', '.join(w['terms'])}]")
        md.append("")
    Path(path).write_text("\n".join(md))


def _write_csv(path, result):
    cy = result.get("current_year", 2026)
    panel_ids = {c.id for c, *_ in result["panel"]}
    with Path(path).open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["rank", "name", "kind", "score", "in_panel", "career_stage",
                     "active", "institution", "country", "disciplines_matched",
                     "core_credit", "core_breadth", "core_lead_works", "method_credit",
                     "recency", "works_count", "h_index", "orcid", "openalex",
                     "author_topics", "evidence"])
        for i, (cand, sc, kind) in enumerate(result["all_rows"], 1):
            aff, ctry = current_affiliation(cand)
            ev = " || ".join(f"{w['title']} ({w['journal']} {w['year']}: "
                             f"{','.join(w['terms'])})" for w in _evidence(cand, 5))
            p = cand.prof or {}
            wr.writerow([i, cand.name, kind, sc["score"],
                         "yes" if cand.id in panel_ids else "",
                         career_stage(p, cy), "yes" if is_active(p, cy) else "no",
                         aff, ctry, "; ".join(_disciplines_matched(cand)),
                         sc["core_credit"], sc["core_breadth"], sc["core_lead_works"],
                         sc["method_credit"], sc["recency"], p.get("works_count"),
                         p.get("h_index"), cand.orcid or "",
                         f"https://openalex.org/{cand.id}",
                         "; ".join(p.get("topics") or []), ev])


def _write_contacts(path, result):
    """A paste-ready contact worksheet for the suggested panel — the fastest path
    from a shortlist to Manuscript Central invitations. One row per panel member:
    email (public ORCID, when available), current affiliation + role, country,
    ORCID/OpenAlex links, and ready-made Google/Scholar search URLs for any gaps.
    Ordered to match the panel (best fit first).
    """
    cy = result.get("current_year", 2026)
    with Path(path).open("w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["panel_rank", "name", "career_stage", "email", "email_source",
                     "affiliation", "affiliation_source", "role", "country",
                     "orcid", "openalex", "google_search", "scholar_search"])
        for i, (cand, sc, kind, why) in enumerate(result["panel"], 1):
            rec = _contact_record(cand, result)
            wr.writerow([i, rec["name"], career_stage(cand.prof, cy),
                         rec["email"], rec["email_source"],
                         rec["affiliation"], rec["affiliation_source"], rec["role"],
                         rec["country"], rec["orcid"], rec["openalex"],
                         rec["google_search"], rec["scholar_search"]])


def _write_raw(path, result):
    out = []
    panel_ids = {c.id for c, *_ in result["panel"]}
    for cand, sc, kind in result["all_rows"]:
        aff, ctry = current_affiliation(cand)
        out.append({
            "id": cand.id, "name": cand.name, "orcid": cand.orcid, "kind": kind,
            "in_panel": cand.id in panel_ids, "affiliation": aff, "country": ctry,
            "disciplines_matched": _disciplines_matched(cand), **sc,
            "works_count": (cand.prof or {}).get("works_count"),
            "h_index": (cand.prof or {}).get("h_index"),
            "topics": (cand.prof or {}).get("topics"),
            "evidence": [{"title": w["title"], "year": w["year"], "journal": w["journal"],
                          "discipline": w["discipline"], "lead": w["lead"],
                          "terms": {t: i["strength"] for t, i in w["terms"].items()}}
                         for w in _evidence(cand, 8)],
        })
    Path(path).write_text(json.dumps(out, indent=2))
