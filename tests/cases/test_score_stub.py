"""AC9 (last clause) for specs/case-consolidation.md: `aml score` is still a stub in 7a.

Kept in its own file because specs/case-prioritization.md (7c) replaces the stub: delete this
file when `aml score` is implemented.
"""

from __future__ import annotations

from .helpers import cli


def test_ac9_score_is_still_a_stub_until_7c() -> None:
    result = cli("score")
    assert result.exit_code == 1, result.output
    assert "arrives in Phase 7" in result.stderr
