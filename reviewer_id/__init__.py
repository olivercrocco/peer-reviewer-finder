"""reviewer_id — find well-matched, conflict-free, diverse peer reviewers via OpenAlex.

A discipline-general pipeline: given a manuscript (title, abstract, tiered search
terms) and the submitting authors' institutions, it searches a configurable
registry of scholarly journals for authors whose published work genuinely matches
the manuscript, screens conflicts of interest, and proposes a relevance-ranked,
institution- and country-diverse reviewer panel.
"""

__version__ = "0.2.0"
