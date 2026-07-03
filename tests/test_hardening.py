"""Unit tests for the security-hardening changes (issue #1, F2-F5).

Run directly or under pytest:
    python tests/test_hardening.py
    python -m pytest tests/test_hardening.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewer_id.report import _safe_slug
from reviewer_id.openalex import OpenAlex, _valid_issn
from reviewer_id.orcid import ORCID
from reviewer_id.coi import _valid_orcid
from reviewer_id.search import find_submission
from reviewer_id.score import career_stage, academic_age


# ---- F2: a spec-supplied slug can't escape the output directory ----
def test_safe_slug_blocks_traversal():
    assert _safe_slug("../../etc/passwd") == "passwd"   # path components dropped
    assert _safe_slug("/abs/evil") == "evil"
    assert _safe_slug("..") == "output"
    assert _safe_slug("") == "output"
    assert _safe_slug(None) == "output"
    assert _safe_slug("My Paper #1") == "My_Paper__1"
    assert _safe_slug("platform_work_ai_hrd") == "platform_work_ai_hrd"   # normal slug intact


# ---- F4: ISSN / ORCID validated before being interpolated into a query ----
def test_valid_issn():
    assert _valid_issn("0007-1234")
    assert _valid_issn("1234-567X")
    assert not _valid_issn("not-an-issn")
    assert not _valid_issn("0007-1234'; DROP")
    assert not _valid_issn("")


def test_valid_orcid():
    assert _valid_orcid("0000-0001-8472-1224") == "0000-0001-8472-1224"
    assert _valid_orcid("https://orcid.org/0000-0001-8472-1224") == "0000-0001-8472-1224"
    assert _valid_orcid("0000-0001-8472-123X") == "0000-0001-8472-123X"
    assert _valid_orcid("javascript:alert(1)") is None
    assert _valid_orcid("0000-0001") is None
    assert _valid_orcid(None) is None


# ---- F3: get() pins absolute URLs to the OpenAlex host ----
def test_get_rejects_non_openalex_url():
    client = OpenAlex(email="")
    raised = False
    try:
        client.get("https://evil.example/redirect")
    except ValueError:
        raised = True
    assert raised, "get() must refuse a non-OpenAlex absolute URL"


# ---- F3 (ORCID client): get() pins absolute URLs to the ORCID host ----
def test_orcid_get_rejects_non_orcid_url():
    client = ORCID()
    raised = False
    try:
        client.get("https://evil.example/0000-0001-8472-1224/email")
    except ValueError:
        raised = True
    assert raised, "ORCID.get() must refuse a non-ORCID absolute URL"


# ---- Career stage keys off academic age, not lifetime output ----
def test_career_stage_uses_academic_age():
    # ~5 years in the field with modest output -> early-career, even though the old
    # rule (h<=10 AND wc<=30) would already agree here.
    early = {"h_index": 6, "works_count": 12,
             "counts_by_year": [{"year": y, "works_count": 2} for y in range(2021, 2027)]}
    assert career_stage(early, current_year=2026) == "early-career"

    # Prolific but RECENT (first pub 2020): the old output-only rule (wc>=100) called
    # this "senior"; academic age (6 yrs) correctly keeps it out of senior.
    prolific_recent = {"h_index": 18, "works_count": 130,
                       "counts_by_year": [{"year": y, "works_count": 20} for y in range(2020, 2027)]}
    assert career_stage(prolific_recent, current_year=2026) != "senior"

    # Long in the field -> senior.
    senior = {"h_index": 28, "works_count": 90,
              "counts_by_year": [{"year": y, "works_count": 4} for y in range(2004, 2027)]}
    assert career_stage(senior, current_year=2026) == "senior"

    # academic_age reads the earliest ACTIVE year; empty data -> None (falls back).
    assert academic_age({"counts_by_year": [{"year": 2019, "works_count": 0},
                                            {"year": 2022, "works_count": 3}]},
                        current_year=2026) == 4
    assert academic_age({}, current_year=2026) is None


# ---- F5: find_submission tolerates partial OpenAlex responses ----
class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *a, **k):
        return self.payload


def test_find_submission_handles_partial_authorship():
    payload = {"results": [{
        "id": "https://openalex.org/W1",
        "title": "Psychological Safety in Remote Teams",
        "publication_year": 2024,
        "authorships": [
            {},                                                       # no 'author' -> skipped, not a crash
            {"author": {}},                                           # author without 'id' -> skipped
            {"author": {"id": "https://openalex.org/A9", "display_name": "Jane Doe"}},
        ],
    }]}
    sub = find_submission(_FakeClient(payload), "Psychological Safety in Remote Teams")
    assert sub is not None
    assert sub["id"] == "https://openalex.org/W1"
    assert sub["authors"] == [("A9", "Jane Doe")]                     # only the well-formed authorship


# ---- Panel selection caps senior scholars ----
class _FakeCand:
    def __init__(self, cid, prof):
        self.id = cid
        self.orcid = ""
        self.prof = prof
        self.works = {}


def _prof(h, first_year, inst, country):
    return {"h_index": h, "works_count": h * 4,
            "counts_by_year": [{"year": y, "works_count": 3} for y in range(first_year, 2027)],
            "last_inst": inst, "last_inst_id": inst, "last_country": country}


def test_diversify_caps_seniors():
    from reviewer_id.diversify import select_panel
    # two high-scoring seniors + two mid-career; scores favor the seniors.
    seniors = [(_FakeCand("S1", _prof(30, 2005, "InstA", "US")),
                {"score": 100.0, "method_credit": 0, "method_primary_breadth": 0, "method_generic_breadth": 0}, "Topic"),
               (_FakeCand("S2", _prof(31, 2004, "InstB", "GB")),
                {"score": 99.0, "method_credit": 0, "method_primary_breadth": 0, "method_generic_breadth": 0}, "Topic")]
    mids = [(_FakeCand("M1", _prof(12, 2013, "InstC", "NL")),
             {"score": 10.0, "method_credit": 0, "method_primary_breadth": 0, "method_generic_breadth": 0}, "Topic"),
            (_FakeCand("M2", _prof(13, 2012, "InstD", "CN")),
             {"score": 9.0, "method_credit": 0, "method_primary_breadth": 0, "method_generic_breadth": 0}, "Topic")]
    ranked = seniors + mids
    graph = {c.id: set() for c, *_ in ranked}
    reqs = {"size": 3, "max_per_institution": 9, "min_countries": 0, "min_disciplines": 0,
            "min_method_experts": 0, "min_early_career": 0, "min_mid_career": 0,
            "min_senior": 0, "max_senior": 1}
    chosen, scorecard = select_panel(ranked, graph, reqs)
    stages = [career_stage(c.prof) for c, *_ in chosen]
    assert len(chosen) == 3
    assert stages.count("senior") == 1, f"max_senior=1 should cap seniors, got {stages}"
    assert stages.count("mid-career") == 2
    assert scorecard["senior"] == (1, 0) and scorecard["mid_career"] == (2, 0)


# ---- ORCID: most-current employment is preferred over ended ones ----
def test_orcid_prefers_current_employment():
    client = ORCID()
    payload = {"affiliation-group": [
        {"summaries": [{"employment-summary": {
            "organization": {"name": "Old University", "address": {"country": "US"}},
            "role-title": "Postdoc", "end-date": {"year": {"value": "2019"}}}}]},
        {"summaries": [{"employment-summary": {
            "organization": {"name": "Current University", "address": {"country": "GB"}},
            "role-title": "Associate Professor", "end-date": None}}]},
    ]}
    client.get = lambda path: payload           # stub the network call
    org, role, dept, country = client.current_employment("0000-0001-8472-1224")
    assert org == "Current University"
    assert role == "Associate Professor"
    assert country == "GB"
    # a malformed ORCID is rejected before any lookup
    assert client.current_employment("not-an-orcid") == ("", "", "", "")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
