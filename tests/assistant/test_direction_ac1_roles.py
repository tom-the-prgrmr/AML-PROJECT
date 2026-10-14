"""AC1 for specs/assistant-direction-check.md: facts.account_roles."""

from __future__ import annotations

import pytest

from .dir_helpers import (
    A315,
    A553,
    A941,
    S_CAN,
    S_CHAIN,
    S_DIR1,
    S_DIR1_ASCII,
    S_DIR1_EN,
    S_EN,
    S_OUT,
    S_REL,
    S_SPEC2,
    S_TXN,
    facts,
    roles,
)

CASES = [
    ("dir1_accented", S_DIR1, {A315: {"dst"}, A941: {"src"}}),
    ("dir1_ascii", S_DIR1_ASCII, {A315: {"dst"}, A941: {"src"}}),
    ("dir1_english", S_DIR1_EN, {A315: {"dst"}, A941: {"src"}}),
    ("spec2_comma_blocks_verb_rule", S_SPEC2, {A315: {"src"}}),
    ("out", S_OUT, {A315: {"src"}, A941: {"dst"}}),
    ("english_sent_to", S_EN, {A315: {"src"}, A941: {"dst"}}),
    ("txn_sentence", S_TXN, {A315: {"src"}, A941: {"dst"}}),
    ("chain", S_CHAIN, {A941: {"src"}, A553: {"dst"}, A315: {"dst"}}),
    (
        "two_verbs",
        "Tài khoản A3154676584 nhận tiền từ A5538166070 và chuyển cho A9418747931.",
        {A315: {"dst"}, A553: {"src"}, A941: {"dst"}},
    ),
    (
        "duoc_chuyen_wins_over_chuyen",
        "Tài khoản A3154676584 được chuyển 5,000,000 VND.",
        {A315: {"dst"}},
    ),
    ("related_to_is_no_direction", S_REL, {}),
    ("modal_co_the_is_no_role", S_CAN, {}),
]


@pytest.mark.parametrize(("name", "text", "expected"), CASES, ids=[c[0] for c in CASES])
def test_dir_ac1_account_roles(name: str, text: str, expected: dict[str, set[str]]) -> None:
    """Given a sentence, When account_roles runs on ACC3, Then roles are as stated."""
    assert roles(text) == expected


def test_dir_ac1_ids_are_case_insensitive_and_keys_keep_the_accounts_spelling() -> None:
    """Given a lower-case id, When account_roles runs, Then the key keeps its spelling."""
    got = facts().account_roles("a3154676584 nhận tiền.", {A315})
    assert {k: set(v) for k, v in got.items()} == {A315: {"dst"}}
    assert list(got) == [A315]
