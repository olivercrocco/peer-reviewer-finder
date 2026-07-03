"""Thin, host-pinned client for the public ORCID API (pub.orcid.org).

Used only to enrich the *recommended reviewers* with their own PUBLIC ORCID data:
a contact email if the researcher chose to make it public, and their current
employer/role (often fresher than OpenAlex's last-known institution).

Confidentiality: this never sends manuscript text, submitting-author identities, or
the editor's email. The only data transmitted is a candidate reviewer's own public
ORCID iD — a public identifier. It is opt-in (``--contacts``) and, by default, runs
only for the small suggested panel. The public API needs no key or token.

Like the OpenAlex client, requests are pinned to a single host so a data-influenced
value can't redirect them elsewhere, with timeouts and default TLS verification.
"""

import time
from urllib.parse import urlparse

import requests

from .coi import _valid_orcid

BASE = "https://pub.orcid.org/v3.0"


class ORCID:
    def __init__(self, tries=3, timeout=30):
        self.tries = tries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "peer-reviewer-finder (reviewer contact lookup)",
        })

    def get(self, path):
        """GET a public ORCID endpoint, pinned to the ORCID host, with light retry.

        Returns {} on 404/gone or after exhausting retries, so a missing record
        never crashes the run.
        """
        if path.startswith("http"):
            # Pin absolute URLs to the ORCID host (mirrors OpenAlex.get).
            if urlparse(path).netloc != urlparse(BASE).netloc:
                raise ValueError(f"refusing to fetch a non-ORCID URL: {path}")
            url = path
        else:
            url = f"{BASE}/{path.lstrip('/')}"
        for attempt in range(self.tries):
            try:
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (404, 409, 410):
                    return {}
                if r.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
            except requests.RequestException:
                if attempt == self.tries - 1:
                    return {}
                time.sleep(1.0 * (attempt + 1))
        return {}

    def public_email(self, orcid):
        """First public email on the record, or "" (most researchers keep it private)."""
        oid = _valid_orcid(orcid)
        if not oid:
            return ""
        data = self.get(f"{oid}/email")
        for e in (data.get("email") or []):
            addr = e.get("email")
            if addr:
                return addr
        return ""

    def current_employment(self, orcid):
        """(organization, role, department, country) for the most current employment
        (no end-date), else the most recent one. Empty strings if none is public."""
        oid = _valid_orcid(orcid)
        if not oid:
            return ("", "", "", "")
        data = self.get(f"{oid}/employments")
        best, best_key = None, None
        for group in (data.get("affiliation-group") or []):
            for s in (group.get("summaries") or []):
                emp = s.get("employment-summary") or {}
                end = emp.get("end-date")
                # a current post (no end-date) sorts ahead of ended ones; among
                # ended ones, the most recent end year wins.
                if not end:
                    key = (0, 0)
                else:
                    try:
                        end_year = int((end.get("year") or {}).get("value") or 0)
                    except (TypeError, ValueError):
                        end_year = 0
                    key = (1, -end_year)
                if best_key is None or key < best_key:
                    best_key, best = key, emp
        if not best:
            return ("", "", "", "")
        org = best.get("organization") or {}
        addr = org.get("address") or {}
        return (org.get("name") or "", best.get("role-title") or "",
                best.get("department-name") or "", addr.get("country") or "")

    def contact(self, orcid):
        """Public contact bundle for one ORCID iD."""
        org, role, dept, country = self.current_employment(orcid)
        return {
            "email": self.public_email(orcid),
            "affiliation": org, "role": role, "department": dept, "country": country,
        }


def fetch_contacts(orcids, log=print, pause=0.2):
    """Fetch public contact info for a small set of ORCID iDs (the panel).

    Returns {bare_orcid_id: {email, affiliation, role, department, country}} for
    every well-formed, resolvable iD. Skips malformed iDs silently.
    """
    client = ORCID()
    out, n_email = {}, 0
    for orcid in orcids or []:
        oid = _valid_orcid(orcid)
        if not oid or oid in out:
            continue
        info = client.contact(oid)
        out[oid] = info
        if info.get("email"):
            n_email += 1
        time.sleep(pause)
    log(f"  ORCID public records: {len(out)} looked up, {n_email} public email(s) found.")
    return out
