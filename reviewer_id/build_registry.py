"""Build journals.yaml from a cross-discipline OpenAlex discovery dump.

Independently re-verifies every proposed journal against the OpenAlex /sources
endpoint (batched), so the registry's ids, names, ISSNs, and works_counts are
authoritative regardless of how the discovery was produced. Dedupes journals that
appear in several disciplines (keeping the highest tier and merging disciplines).

    python -m reviewer_id.build_registry --src data_discovery_raw.json --out journals.yaml
"""

import argparse
import json
from pathlib import Path

import yaml

from .openalex import OpenAlex

TIER_RANK = {"flagship": 3, "core": 2, "adjacent": 1}


def build(src, out, email=None):
    groups = json.loads(Path(src).read_text())
    oa = OpenAlex(email=email)

    by_id = {}          # canonical OpenAlex id -> aggregated proposal
    unresolved = []

    def slot(jid):
        return by_id.setdefault(jid, {"disciplines": set(), "tiers": set(),
                                      "relevance": {}, "names": set(), "issn": set()})

    def add(jid, disc, j):
        rec = slot(jid)
        rec["disciplines"].add(disc)
        rec["tiers"].add(j.get("tier", "adjacent"))
        if j.get("relevance"):
            rec["relevance"][disc] = j["relevance"]
        if j.get("name"):
            rec["names"].add(j["name"])
        for s in (j.get("issn") or []):
            rec["issn"].add(s)

    for g in groups:
        disc = g["discipline"]
        for j in g.get("journals", []):
            jid = (j.get("openalex_id") or "").strip()
            if jid.startswith("S"):
                add(jid, disc, j)
            else:
                unresolved.append((disc, j))

    for disc, j in unresolved:
        s = oa.resolve_source(issns=j.get("issn"), name=j.get("name"))
        if s and s.get("id"):
            add(s["id"], disc, j)
        else:
            print(f"  UNRESOLVED (dropped): {j.get('name')}")

    # batch-verify every id against OpenAlex
    verified = {}
    ids = list(by_id)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = oa.get("sources", {
            "filter": "openalex_id:" + "|".join(chunk), "per-page": 50,
            "select": "id,display_name,issn,issn_l,works_count,type,country_code,homepage_url",
        })
        for s in data.get("results", []):
            verified[s["id"].split("/")[-1]] = s

    registry, dropped = [], []
    seen_issn_l = {}
    for jid, rec in by_id.items():
        s = verified.get(jid)
        if not s:
            dropped.append((jid, sorted(rec["names"]), "not found on verify"))
            continue
        if s.get("type") not in ("journal", "conference", None):
            dropped.append((jid, s.get("display_name"), f"type={s.get('type')}"))
            continue
        issn_l = s.get("issn_l")
        if issn_l and issn_l in seen_issn_l:          # same journal, different id
            existing = seen_issn_l[issn_l]
            existing["disciplines"] = sorted(set(existing["disciplines"]) | rec["disciplines"])
            continue
        tier = sorted(rec["tiers"], key=lambda t: -TIER_RANK.get(t, 0))[0]
        entry = {
            "openalex_id": jid,
            "name": s.get("display_name"),
            "issn": s.get("issn") or sorted(rec["issn"]),
            "disciplines": sorted(rec["disciplines"]),
            "tier": tier,
            "works_count": s.get("works_count"),
            "country": s.get("country_code"),
            "relevance": "; ".join(sorted(set(rec["relevance"].values())))[:240],
        }
        registry.append(entry)
        if issn_l:
            seen_issn_l[issn_l] = entry

    registry.sort(key=lambda r: (-TIER_RANK.get(r["tier"], 0), -(r["works_count"] or 0)))

    header = (
        "# Journal registry for peer-reviewer-finder\n"
        "# Auto-built by `python -m reviewer_id.build_registry` and re-verified against\n"
        "# the OpenAlex /sources API. Edit freely; add a journal by resolving its id at\n"
        "# https://api.openalex.org/sources/issn:XXXX-XXXX and appending an entry below.\n"
        "# Fields: openalex_id, name, issn, disciplines[], tier (flagship|core|adjacent),\n"
        "#         works_count, country, relevance.\n\n")
    Path(out).write_text(header + yaml.safe_dump({"journals": registry},
                                                 sort_keys=False, allow_unicode=True))

    print(f"\nVerified journals: {len(registry)}  ->  {out}")
    if dropped:
        print(f"Dropped {len(dropped)}:")
        for d in dropped:
            print("   ", d)
    from collections import Counter
    disc_counts = Counter(d for r in registry for d in r["disciplines"])
    print("\nBy discipline (journals can count in more than one):")
    for d, n in disc_counts.most_common():
        print(f"  {n:>3}  {d}")
    return registry


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data_discovery_raw.json")
    ap.add_argument("--out", default="journals.yaml")
    ap.add_argument("--email", default=None)
    args = ap.parse_args()
    build(args.src, args.out, email=args.email)
