# peer-reviewer-finder

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20448662.svg)](https://doi.org/10.5281/zenodo.20448662)

Find well-matched, conflict-free, and diverse peer reviewers for a manuscript in
**human resource development and adjacent fields**, using
[OpenAlex](https://openalex.org). Built for journal editors in HRD, adult and
continuing education, management, and related fields who need a defensible
shortlist quickly. The journal registry is configurable, so it can be retargeted
to other fields.

Given a manuscript (title, abstract, and a few tiered keywords) plus the
submitting authors' institutions, the pipeline:

- searches a configurable registry of **83 scholarly journals across 6
  disciplines** (HRD, Adult & Continuing Education, Higher Education, Management
  & Organizational Behavior, Career/Vocational/Workforce Development, and
  International & Comparative Education) for authors whose published work
  **genuinely** matches the manuscript;
- screens **conflicts of interest** — excludes anyone from a submitting author's
  institution, and ensures the recommended reviewers haven't co-authored with one
  another;
- proposes a **relevance-ranked, institution- and country-diverse panel**, plus a
  longer ranked list to pick alternates from.

It does not contact reviewers or make decisions — it produces evidence and a
shortlist; the editor decides.

## Confidentiality (built for unpublished manuscripts)

This tool runs **entirely on your machine** — no account, no server, no telemetry —
and **sends no manuscript text to any AI/LLM**. It only searches the
[OpenAlex](https://openalex.org) scholarly database by keyword.

**Confidential mode is ON by default.** In it, the only manuscript-derived data that
leaves your computer is your **generic topic keywords** — never the title, abstract,
author identities, or your email. Use `--no-confidential` only for already-published
work. Your manuscript specs and generated shortlists are git-ignored, so they are
never uploaded even though this repo is public.

> One line for authors/IT: *"It runs locally, sends no manuscript text to any AI, and
> by default transmits only generic topic keywords to the OpenAlex scholarly database."*

Full details and a transmission table: **[CONFIDENTIALITY.md](CONFIDENTIALITY.md)**.

## Install

```bash
pip install -r requirements.txt          # requests + PyYAML
export REVIEWER_ID_EMAIL="you@example.edu"  # opts into OpenAlex's faster "polite pool"
```

No API key is required.

## Quickstart

```bash
# 1. Describe the submission
cp articles/example.template.json articles/my_submission.json
#    edit it: title, abstract, tiered terms, and author_institutions

# 2. Run
python -m reviewer_id --article articles/my_submission.json
#    (or: python find_reviewers.py --article articles/my_submission.json)
```

Outputs land in `output/<slug>_*`:

| file | what it is |
|---|---|
| `<slug>_panel.md` | **the deliverable** — suggested diverse panel + COI summary |
| `<slug>_reviewers.md` | full ranked report with evidence per candidate |
| `<slug>_candidates.csv` | every scored candidate; re-sort in a spreadsheet |
| `<slug>_raw.json` | matched works + per-term match strength (audit trail) |

Useful flags: `--disciplines "Human Resource Development,Higher Education"` to
narrow the pool, `--panel 5`, `--top 30`, `--list-disciplines`.

## The article spec

A small JSON file (see [`articles/example.template.json`](articles/example.template.json)).
The only real work is **tiering the keywords** — this is what makes the matching good:

```jsonc
{
  "slug": "my_submission",
  "title": "...", "abstract": "...",

  "core_terms":          [ /* the paper's defining subject — weighted x3 */ ],
  "secondary_terms":     [ /* related constructs it touches — x1 */ ],
  "method_primary_terms":[ /* its actual method, e.g. bibliometrics — x2 */ ],
  "method_generic_terms":[ /* common methods (weak signal): lit review — x0.8 */ ],
  "context_terms":       [ /* setting, e.g. higher education — x0.4 */ ],

  "disciplines": null,            // null = all; or a subset of registry disciplines
  "journals": null,               // optional: restrict to named journals/ids

  "author_institutions": ["University of X", "Y State University"],  // COI exclusion (also drops the authors, no names)
  "author_orcids": [],            // optional: ORCID iDs (not names) -> exclude authors + recent co-authors
  "screen_coauthors": false,      // opt-in in confidential mode (transmits the ORCIDs)
  "exclude_author_names": [], "exclude_author_ids": [],              // manual COI overrides

  "panel": {                      // optional scorecard the suggested panel tries to satisfy
    "size": 9, "max_per_institution": 1, "min_countries": 4,
    "min_disciplines": 2, "min_method_experts": 1,
    "min_early_career": 1, "min_senior": 1
  }
}
```

### The panel scorecard

A good panel is a set of boxes, not just the top-N by score. The `panel` block
declares targets — institution and country spread, **disciplinary** spread (uses the
cross-discipline pool), **method-expertise** coverage (matched to the manuscript's
own method), and a **senior / early-career** mix (via an h-index + output proxy). The
selector fills unmet boxes first, then takes the best remaining candidates, and the
report shows a scorecard (`✓ countries 6/4 · ✓ method experts 2/1 · …`). Boxes that
can't be filled from the pool are flagged, not hidden.

The proposed set defaults to **9 reviewers, ranked by best fit** — a deeper bench,
since invitation response rates are low and some candidates may be over-tapped.

### Reviewer over-use ledger

Keep a local `reviewer-ledger.csv` (git-ignored) of reviewers you've recently
invited, who declined, or who are otherwise ineligible — the tool drops them so it
stops re-surfacing the same tapped-out names. Columns:
`name, orcid, openalex_id, last_invited, status, note` (see
[`reviewer-ledger.example.csv`](reviewer-ledger.example.csv)). A dated entry cools
down and becomes eligible again after `--ledger-cooldown` months (default 12);
`status` of `declined`/`blocked` skips permanently. It's auto-used if the file
exists; `--no-ledger` ignores it. Entirely local and confidential — matched on your
machine, never transmitted.

## How matching works (and why it's trustworthy)

1. **Search** each term across the journal pool (OpenAlex relevance search, top-N per term).
2. **Precision gate** — a term earns credit for a work only if its exact phrase is
   in the **title** (2.0) or **abstract** (1.0), or all its content tokens appear
   (0.5). Pure fulltext/relevance hits are discarded. *This is the crucial step:*
   without it, a field's prolific generalists match every broad term loosely and
   bury the real subject-matter experts.
3. **Tier weights** make a real match on a distinctive `core` term count far more
   than one on a generic term.
4. **Aggregate per author**, capping to the strongest few works so sheer volume
   can't dominate; add small bonuses for core-term breadth, recency, and a
   credible publication record.
5. **Enrich** the top candidates (works-count, h-index, current affiliation, topics).
6. **Screen COI** — drop submission self-matches, manual exclusions, and anyone at a
   submitting author's institution (matched by OpenAlex institution id, with a
   normalized-name fallback). Optionally, given the authors' **ORCID iDs** (not names),
   also exclude the authors and their recent co-authors. Reviewers in your local
   **over-use ledger** (recently invited, declined, ineligible) are dropped too.
7. **Diversify against the scorecard** — greedily select a panel that maximizes
   relevance while filling the `panel` targets (institution/country/discipline spread,
   method coverage, senior/early-career mix) and never pairing two people who
   co-authored a matched work. Unfilled boxes are reported.

## The journal registry

[`journals.yaml`](journals.yaml) is the searchable pool. Each entry carries its
OpenAlex id, ISSNs, the discipline(s) it belongs to, a tier
(`flagship`/`core`/`adjacent`), and a works count. List what's loaded:

```bash
python -m reviewer_id --list-disciplines
```

**Extend it** by appending an entry (resolve a journal at
`https://api.openalex.org/sources/issn:XXXX-XXXX`), or regenerate it from a
discovery dump:

```bash
python -m reviewer_id.build_registry --src data_discovery_raw.json --out journals.yaml
```

The shipped registry was built by curating leading journals per discipline and
re-verifying every one against the OpenAlex `/sources` API.

## Caveats

- **Verify each invitee's current affiliation and email** before inviting. OpenAlex's
  "last known institution" lags; the pipeline prefers the most-recent matched-work
  affiliation, but disambiguation errors still happen.
- **Exact-phrase gating can under-credit** authors who use synonyms (e.g. a scholar
  who writes "turnover intention" won't match the term "intention to quit"). The
  report shows each candidate's author-level OpenAlex topics as a cross-check.
- **Per-term results are capped** (`--per-query`, default 100, relevance-ranked).
  With a very broad pool, a common low-tier term may be truncated toward mega-journals;
  distinctive `core` terms are unaffected. Raise `--per-query` if needed.
- **Unpublished submissions** can't be auto-screened for self-matches — supply
  `exclude_author_names`/`author_institutions` and screen co-authors manually.

## License

MIT — see [LICENSE](LICENSE).
