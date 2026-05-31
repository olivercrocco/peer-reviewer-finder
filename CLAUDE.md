# peer-reviewer-finder — project guide

A local, confidential command-line tool that recommends well-matched, conflict-free, and
diverse peer reviewers for a manuscript in **human resource development and adjacent
fields**, using the public OpenAlex API. The editor decides; this produces the evidence and
a defensible shortlist. (A separate JavaScript browser version of the same idea lives in
the `olivercrocco-site` repo, not here.)

## What it does

Given a manuscript spec (title, abstract, tiered keywords, author institutions), it searches
a configurable journal registry (~97 journals across HRD and adjacent disciplines) on
OpenAlex for genuinely-matching authors, screens conflicts of interest (shared institution;
co-authorship between recommended reviewers), and proposes a relevance-ranked, institution-
and country-diverse panel plus alternates.

## Architecture

- `reviewer_id/` — the package: `cli.py` (entry + orchestration), `openalex.py` (thin REST
  client + entity resolvers), `search.py` (term search + submission lookup), `coi.py`
  (conflict screening), `score.py`, `report.py` (writes panel / report / CSV / raw outputs),
  `config.py`.
- `find_reviewers.py` — thin entrypoint (identical to `python -m reviewer_id`).
- The journal registry (YAML) is the searchable journal set.

## Running and testing

```bash
python -m reviewer_id --article articles/my_submission.json
python -m pytest                  # includes tests/test_hardening.py
```

## Conventions & constraints

- **Confidential by design:** confidential mode (the default) sends OpenAlex only generic
  topic keywords — never the title, abstract, author identities, or email. Never weaken this.
- **Local only:** no network beyond the OpenAlex public API; no AI/LLM; no telemetry. HTTP is
  host-pinned to `api.openalex.org` with timeouts and default TLS verification — keep it
  pinned (see `OpenAlex.get`).
- **No secrets / no PII committed:** `articles/*`, `output/`, and the reviewer ledger are
  git-ignored; only `*.template.*` / `example.*` are tracked.
- **Input hygiene:** validate spec-supplied values before interpolating them into queries
  (ORCID/ISSN format checks; the output slug is sanitized); use `.get()` guards for partial
  OpenAlex responses; keep dependency ranges pinned in `requirements.txt`.
- **Voice:** plain and precise. The tool supplies evidence; it does not "decide."
