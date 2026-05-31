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
from reviewer_id.coi import _valid_orcid
from reviewer_id.search import find_submission


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


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
