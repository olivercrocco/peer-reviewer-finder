"""Command-line entrypoint.

    python -m reviewer_id --article articles/my_submission.json
    python -m reviewer_id --article articles/my_submission.json --disciplines "Human Resource Development,Higher Education"
    python -m reviewer_id --list-disciplines
"""

import argparse
import json
import sys
from pathlib import Path

from .config import all_disciplines, load_registry, LEDGER_PATH, REGISTRY_PATH
from .openalex import OpenAlex
from .pipeline import run
from .report import write_all


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reviewer_id",
                                 description="Find matched, conflict-free, diverse peer reviewers via OpenAlex.")
    ap.add_argument("--article", help="Path to the article spec JSON.")
    ap.add_argument("--registry", default=str(REGISTRY_PATH), help="Journal registry (YAML/JSON).")
    ap.add_argument("--disciplines", help="Comma-separated disciplines to include (default: all, or the spec's list).")
    ap.add_argument("--top", type=int, default=25, help="How many ranked candidates to report.")
    ap.add_argument("--panel", type=int, default=None, help="Panel size (overrides the spec's panel.size / default 6).")
    ap.add_argument("--per-query", type=int, default=100, help="Top-N relevance-ranked works fetched per term.")
    ap.add_argument("--enrich-top", type=int, default=150, help="How many top candidates to profile-enrich.")
    ap.add_argument("--current-year", type=int, default=2026, help="Used for recency scoring.")
    ap.add_argument("--out", default="output", help="Output directory.")
    ap.add_argument("--email", default=None, help="Contact email for the OpenAlex polite pool (or set REVIEWER_ID_EMAIL). Ignored in confidential mode.")
    ap.add_argument("--confidential", action=argparse.BooleanOptionalAction, default=None,
                    help="Confidential mode (DEFAULT ON): send OpenAlex only generic topic "
                         "terms — never the title, abstract, your email, or author-institution "
                         "names. Use --no-confidential for already-published work.")
    ap.add_argument("--screen-coauthors", action=argparse.BooleanOptionalAction, default=None,
                    help="Exclude the submitting authors + their recent collaborators via "
                         "author_orcids in the spec. In confidential mode this is opt-in "
                         "(it transmits the ORCIDs, not the manuscript).")
    ap.add_argument("--ledger", default=None,
                    help="Path to a reviewer over-use ledger CSV (recently invited / declined / "
                         "ineligible). Auto-used if reviewer-ledger.csv exists. Local & confidential.")
    ap.add_argument("--no-ledger", action="store_true", help="Ignore the over-use ledger.")
    ap.add_argument("--ledger-cooldown", type=int, default=12,
                    help="Months a dated ledger entry stays excluded before becoming eligible again.")
    ap.add_argument("--list-disciplines", action="store_true", help="Print the registry's disciplines and exit.")
    args = ap.parse_args(argv)

    registry = load_registry(args.registry)

    if args.list_disciplines:
        print(f"{len(registry)} journals in {args.registry}\nDisciplines:")
        for d in all_disciplines(registry):
            n = sum(1 for j in registry if d in j.get("disciplines", []))
            print(f"  {n:>3}  {d}")
        return 0

    if not args.article:
        ap.error("--article is required (or use --list-disciplines)")

    spec = json.loads(Path(args.article).read_text())
    if args.disciplines:
        spec["disciplines"] = [d.strip() for d in args.disciplines.split(",") if d.strip()]

    # mode precedence: CLI flag > spec field > default (confidential ON)
    confidential = args.confidential if args.confidential is not None else spec.get("confidential", True)
    if args.screen_coauthors is not None:
        spec["screen_coauthors"] = args.screen_coauthors

    # resolve the over-use ledger: --no-ledger > --ledger > spec > default file
    if args.no_ledger:
        ledger_path = None
    elif args.ledger:
        ledger_path = args.ledger
    elif spec.get("reviewer_ledger"):
        ledger_path = spec["reviewer_ledger"]
    elif Path(LEDGER_PATH).exists():
        ledger_path = str(LEDGER_PATH)
    else:
        ledger_path = None
    cooldown = spec.get("ledger_cooldown_months", args.ledger_cooldown)

    # confidential mode sends no mailto (email="" suppresses it); otherwise use --email/env
    client = OpenAlex(email="" if confidential else args.email)
    result = run(spec, client, registry, top=args.top, panel_size=args.panel,
                 per_query=args.per_query, enrich_top=args.enrich_top,
                 current_year=args.current_year, confidential=confidential,
                 ledger_path=ledger_path, ledger_cooldown=cooldown)

    slug = spec.get("slug") or Path(args.article).stem
    paths = write_all(result, args.out, slug)

    mode = "CONFIDENTIAL (only topic terms sent)" if confidential else "standard (title lookup + polite pool)"
    print(f"\nMode: {mode}")
    print("Wrote:")
    for k, p in paths.items():
        print(f"  {p}")
    print(f"\nSuggested panel ({len(result['panel'])}):")
    from .coi import current_affiliation
    for i, (cand, sc, kind, why) in enumerate(result["panel"], 1):
        aff, ctry = current_affiliation(cand)
        print(f"  {i}. {cand.name:<26} {kind:<16} {ctry or '--':<4} "
              f"{(aff or '')[:34]:34} [{why}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
