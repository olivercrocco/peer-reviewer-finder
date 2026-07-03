#!/usr/bin/env python3
"""gapfill_contacts.py — fill in the reviewer emails the finder couldn't.

The core reviewer-finder is confidential and host-pinned: it talks only to OpenAlex
and, opt-in, the public ORCID API, and it never scrapes the open web. Most reviewer
emails are not public in ORCID, though, so this companion covers the last mile
WITHOUT putting web scraping inside the hardened pipeline. It is two deterministic,
network-free steps and leaves the actual lookup to you (or an AI assistant with web
access) in between:

  1. prepare  read a run's <slug>_contacts.csv, list the panel members still missing
              an email, and write <slug>_gapfill_worklist.json — each with name,
              affiliation, ORCID/OpenAlex links, and ready-made search URLs.

  2. merge    take the filled-in results (the worklist with emails added, or the JSON
              a web-search assistant returned) and write <slug>_contacts_completed.csv.

Searching a reviewer's public name and institution reveals nothing about the
manuscript, so the lookup between the two steps is confidentiality-safe. This script
itself makes no network calls.

Usage
    python gapfill_contacts.py prepare output/my_submission_contacts.csv
    #  ... fill in emails (see the printed instructions) ...
    python gapfill_contacts.py merge output/my_submission_contacts.csv results.json

`results.json` may be a bare list, the worklist with `email` fields filled in, or the
raw output of the reviewer-email gap-fill workflow (a dict with a `result` list). Each
result item is matched to a panel member by name; recognized fields per item:
    email, email_confidence, email_source_url | email_source, verified,
    current_affiliation | affiliation, notes
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus


def _norm_name(s):
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def _base(contacts_csv):
    """Strip a trailing '_contacts.csv' (or '.csv') to get the output stem."""
    p = Path(contacts_csv)
    stem = p.name
    for suffix in ("_contacts.csv", ".csv"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return p.parent / stem


def _search_urls(name, affiliation):
    q = f'"{name}" {affiliation} email'.strip()
    return (f"https://www.google.com/search?q={quote_plus(q)}",
            f"https://scholar.google.com/scholar?q={quote_plus(name or '')}")


def prepare(contacts_csv):
    rows = list(csv.DictReader(open(contacts_csv, newline="")))
    if not rows:
        sys.exit(f"No rows in {contacts_csv}")
    todo = []
    for r in rows:
        if (r.get("email") or "").strip():
            continue                                  # already have one (e.g. from ORCID)
        google = r.get("google_search") or ""
        scholar = r.get("scholar_search") or ""
        if not google or not scholar:
            google, scholar = _search_urls(r.get("name"), r.get("affiliation"))
        todo.append({
            "name": r.get("name", ""),
            "affiliation": r.get("affiliation", ""),
            "country": r.get("country", ""),
            "orcid": r.get("orcid", ""),
            "openalex": r.get("openalex", ""),
            "google_search": google,
            "scholar_search": scholar,
            "email": "",                              # <- fill this in
            "email_source_url": "",
            "email_confidence": "",
        })
    out = _base(contacts_csv).with_name(_base(contacts_csv).name + "_gapfill_worklist.json")
    out.write_text(json.dumps(todo, indent=2))
    have = len(rows) - len(todo)
    print(f"{len(rows)} panel members; {have} already have an email, {len(todo)} need lookup.")
    print(f"Wrote worklist: {out}")
    if todo:
        print("\nFill the `email` (and ideally `email_source_url`/`email_confidence`) fields for each")
        print("entry from a real public source — a faculty/directory page, ORCID, or a paper's")
        print("corresponding-author line. Do not pattern-guess an address. Then run:")
        print(f"    python {Path(sys.argv[0]).name} merge {contacts_csv} {out}")


def _load_results(results_json):
    data = json.loads(Path(results_json).read_text())
    if isinstance(data, dict):
        data = data.get("result") or data.get("results") or []
    return data if isinstance(data, list) else []


def merge(contacts_csv, results_json):
    rows = list(csv.DictReader(open(contacts_csv, newline="")))
    results = {_norm_name(r.get("name")): r for r in _load_results(results_json)}

    cols = ["panel_rank", "name", "career_stage", "email", "email_confidence",
            "email_source", "email_verified", "affiliation", "country",
            "orcid", "openalex", "google_search", "notes"]
    out = _base(contacts_csv).with_name(_base(contacts_csv).name + "_contacts_completed.csv")
    filled = 0
    with out.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            found = results.get(_norm_name(r.get("name")), {})
            tool_email = (r.get("email") or "").strip()          # ORCID email from the run
            web_email = (found.get("email") or "").strip()
            email = tool_email or web_email
            if email:
                filled += 1
            if tool_email:
                source, conf, verified = "ORCID public", "high", "yes"
            elif web_email:
                source = found.get("email_source_url") or found.get("email_source") or ""
                conf = found.get("email_confidence") or ""
                verified = "yes" if found.get("verified") else ""
            else:
                source = conf = verified = ""
            affiliation = found.get("current_affiliation") or found.get("affiliation") or r.get("affiliation", "")
            wr.writerow({
                "panel_rank": r.get("panel_rank", ""), "name": r.get("name", ""),
                "career_stage": r.get("career_stage", ""), "email": email,
                "email_confidence": conf, "email_source": source, "email_verified": verified,
                "affiliation": affiliation, "country": r.get("country", ""),
                "orcid": r.get("orcid", ""), "openalex": r.get("openalex", ""),
                "google_search": r.get("google_search", ""), "notes": found.get("notes", ""),
            })
    print(f"{len(rows)} panel members; {filled} now have an email.")
    print(f"Wrote completed sheet: {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="gapfill_contacts",
        description="Bridge the reviewer contact sheet's email gaps (no network; the lookup is yours).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare", help="List panel members missing an email -> a worklist JSON.")
    p1.add_argument("contacts_csv", help="A run's <slug>_contacts.csv")
    p2 = sub.add_parser("merge", help="Fold filled-in emails back into a completed sheet.")
    p2.add_argument("contacts_csv", help="The same <slug>_contacts.csv")
    p2.add_argument("results_json", help="The filled worklist, or an assistant's results JSON.")
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        prepare(args.contacts_csv)
    elif args.cmd == "merge":
        merge(args.contacts_csv, args.results_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
