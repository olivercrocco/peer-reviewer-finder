"""Thin OpenAlex REST client + entity resolvers.

OpenAlex needs no API key. Supplying a contact email opts into the faster, more
reliable "polite pool" (https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication).
Set it via the REVIEWER_ID_EMAIL environment variable or pass `email=`.
"""

import os
import time
import requests

BASE = "https://api.openalex.org"


class OpenAlex:
    def __init__(self, email=None, tries=4, timeout=90):
        # email=None -> fall back to env var; email="" -> explicitly send NO mailto
        # (used by confidential mode so queries aren't tied to the editor's identity)
        self.email = os.environ.get("REVIEWER_ID_EMAIL", "") if email is None else email
        self.tries = tries
        self.timeout = timeout
        self.session = requests.Session()
        ua = "peer-reviewer-finder"
        if self.email:
            ua += f" (mailto:{self.email})"
        self.session.headers.update({"User-Agent": ua})

    def get(self, path, params=None):
        """GET an OpenAlex endpoint with retry/backoff on 429 and transient errors."""
        params = dict(params or {})
        if self.email:
            params["mailto"] = self.email
        url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
        for attempt in range(self.tries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
            except requests.RequestException:
                if attempt == self.tries - 1:
                    raise
                time.sleep(1.5 * (attempt + 1))
        return {}

    # -- resolvers -------------------------------------------------------------
    def resolve_source(self, issns=None, name=None):
        """Resolve a journal to its OpenAlex source. Prefer ISSN (exact); fall
        back to a name search and pick the best 'journal'-type match. Returns a
        dict {id, display_name, issn, works_count} or None."""
        for issn in (issns or []):
            data = self.get(f"sources/issn:{issn}")
            if data and data.get("id"):
                return self._source_fields(data)
        if name:
            data = self.get("sources", {"search": name, "per-page": 5})
            results = data.get("results", [])
            journals = [s for s in results if s.get("type") == "journal"] or results
            if journals:
                # choose the closest display-name match
                low = name.lower()
                journals.sort(key=lambda s: (
                    low not in (s.get("display_name") or "").lower(),
                    -(s.get("works_count") or 0)))
                return self._source_fields(journals[0])
        return None

    @staticmethod
    def _source_fields(s):
        return {
            "id": (s.get("id") or "").split("/")[-1],
            "display_name": s.get("display_name"),
            "issn": s.get("issn") or [],
            "works_count": s.get("works_count"),
            "type": s.get("type"),
        }

    def resolve_institution(self, name):
        """Resolve an institution name to its OpenAlex institution id + canonical
        name + country. Returns dict {id, display_name, country_code, ror} or None."""
        data = self.get("institutions", {"search": name, "per-page": 5})
        results = data.get("results", [])
        if not results:
            return None
        low = name.lower()
        results.sort(key=lambda i: (
            low not in (i.get("display_name") or "").lower(),
            -(i.get("works_count") or 0)))
        i = results[0]
        return {
            "id": (i.get("id") or "").split("/")[-1],
            "display_name": i.get("display_name"),
            "country_code": i.get("country_code"),
            "ror": i.get("ror"),
        }

    def fetch_authors(self, author_ids):
        """Batch-fetch author profiles (up to 50 per request)."""
        out = {}
        ids = list(author_ids)
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            data = self.get("authors", {
                "filter": "openalex_id:" + "|".join(chunk),
                "per-page": 50,
                "select": "id,display_name,orcid,works_count,cited_by_count,"
                          "summary_stats,last_known_institutions,topics,counts_by_year",
            })
            for a in data.get("results", []):
                aid = a["id"].split("/")[-1]
                insts = a.get("last_known_institutions") or []
                out[aid] = {
                    "works_count": a.get("works_count"),
                    "cited_by_count": a.get("cited_by_count"),
                    "h_index": (a.get("summary_stats") or {}).get("h_index"),
                    "last_inst": insts[0].get("display_name") if insts else "",
                    "last_inst_id": (insts[0].get("id") or "").split("/")[-1] if insts else "",
                    "last_country": insts[0].get("country_code") if insts else "",
                    "topics": [t.get("display_name") for t in (a.get("topics") or [])[:4]],
                    "counts_by_year": a.get("counts_by_year") or [],
                }
            time.sleep(0.2)
        return out
