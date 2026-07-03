# Confidentiality & data handling

This tool is designed to be used with **unpublished manuscripts under peer
review**. It is built so that confidential manuscript material never leaves your
computer. This page documents exactly what does and does not happen, so editors,
authors, and IT/security reviewers can verify it.

## What this tool is — and is not

- It is a **Python script that searches the [OpenAlex](https://openalex.org)
  scholarly-metadata database** by keyword, the same kind of search a librarian or
  editor performs by hand.
- It is **not an AI/LLM service.** At runtime, no language model is involved and
  **no manuscript text is sent to any AI.** The matching is plain keyword search
  and arithmetic scoring.
- It runs **entirely on your machine.** There is no account, no server, and no
  telemetry. Your manuscript files and the generated shortlists stay local.

## What is sent off your machine

| Data | Sent to OpenAlex? |
|---|---|
| Manuscript **abstract** | **Never** — read locally only |
| Manuscript **title** | **Only in standard mode**, for the self-match check. **Not sent in confidential mode.** |
| Your **tiered topic terms** (e.g. "team learning") | Yes — these drive the search |
| Submitting authors' **institution names** | **Only in standard mode.** Confidential mode matches them locally. |
| Submitting authors' **ORCID iDs** (co-author screening) | **Only if you opt in** (`screen_coauthors` / `--screen-coauthors`) — transmits the ORCID, not the manuscript |
| **Recommended reviewers'** public ORCID iDs (contact lookup) | **Only if you opt in** (`--contacts`) — sent to `pub.orcid.org` to fetch their public email/employer; never the manuscript or submitting authors |
| Your **email** | Only if you set one and are in standard mode (OpenAlex "polite pool") |
| Anything sent to an **AI/LLM** | **Never** |

OpenAlex is operated by [OurResearch](https://ourresearch.org), a US nonprofit.
Its API receives query parameters as part of normal HTTP requests.

## Reviewer contact lookup (`--contacts`, opt-in)

Inviting a reviewer needs an email and affiliation. With `--contacts`, the tool
queries the **public ORCID API** (`pub.orcid.org`) for each member of the suggested
panel to fill in a public email (when the researcher chose to publish one) and their
current employer. This is off by default. When on:

- it sends **only the candidate reviewers' own public ORCID iDs** — public
  identifiers, not manuscript-derived data. The manuscript title, abstract, your
  topic terms, the submitting authors, and your email are **not** sent to ORCID;
- it runs **only for the small recommended panel**, not the whole candidate pool;
- the ORCID client is **host-pinned** to `pub.orcid.org`, with timeouts and TLS
  verification, exactly like the OpenAlex client;
- it is compatible with confidential mode (it concerns reviewers, not your authors).

The `<slug>_contacts.csv` worksheet is written whether or not `--contacts` is set;
without it, the email column is blank and only locally-built search links are
provided (no network). ORCID is operated by a US nonprofit; its public API returns
only data each researcher has chosen to make public.

## Confidential mode (default: ON)

Confidential mode is **on by default**. In it, the only manuscript-derived data
that leaves your machine is your **generic topic keywords** — never the title,
abstract, author identities, or your email. Concretely it:

- **skips the title self-match lookup** (so the title is never transmitted);
- **sends no contact email** (queries aren't tied to your identity);
- **matches author institutions locally** (their names aren't transmitted);
- **leaves ORCID co-author screening off** unless you explicitly opt in (it would
  transmit the author ORCID iDs — though never the manuscript).

Trade-offs (all minor): the submitting authors aren't auto-excluded — list them in
`exclude_author_names` instead — and same-institution COI uses local name matching,
so supply full institution names.

```bash
# confidential (default)
python -m reviewer_id --article articles/my_submission.json

# standard mode — only for already-published work
python -m reviewer_id --article articles/my_submission.json --no-confidential
```

You can also set `"confidential": true|false` in the article spec; the CLI flag
wins over the spec.

## What is never committed to GitHub

The repository is public, but your usage is not. `.gitignore` excludes:

- `output/` — every generated shortlist/report
- `articles/*.json` — your manuscript specs (only the synthetic `example.template.json` is tracked)
- `reviewer-ledger.csv` — your private list of recently-invited / ineligible reviewers
  (matched locally, never transmitted; only the synthetic `reviewer-ledger.example.csv` is tracked)

So pushing the repo never uploads a real title, abstract, author list, or result.
Don't override this with `git add -f`, and don't paste real manuscript text into
the README or commit messages.

## One-line summary for authors/IT

> "The reviewer-finder runs locally, sends no manuscript text to any AI, and in its
> default confidential mode transmits only generic topic keywords to the OpenAlex
> scholarly database — never the title, abstract, or author identities."
