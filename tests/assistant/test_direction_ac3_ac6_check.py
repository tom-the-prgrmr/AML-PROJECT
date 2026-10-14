"""AC3-AC6 for specs/assistant-direction-check.md: check_claim with direction and speculation."""

from __future__ import annotations

from .an_helpers import EV, S_OK1
from .dir_helpers import (
    CHK,
    S_CAN,
    S_CHAIN,
    S_DIR1,
    S_DIR1_ASCII,
    S_DIR1_EN,
    S_EN,
    S_IN,
    S_OUT,
    S_REL,
    S_SPEC2,
    S_TXN,
    validation,
)


def test_dir_ac3_reversed_sentence_one_is_mismatch() -> None:
    """Given D1 (A315 -> A941), When S_DIR1 says A315 received from A941, Then mismatch."""
    for text in (S_DIR1, S_DIR1_ASCII, S_DIR1_EN):
        c = CHK(text, ("E1",))
        assert (c.supported, c.issues, c.refs) == (False, ("direction_mismatch",), ("E1",)), text


def test_dir_ac3_a941_is_only_dst_in_d1_so_citing_e2_too_does_not_help() -> None:
    """Given E1+E2, When S_DIR1 is checked, Then A941 is still only a dst: mismatch."""
    assert CHK(S_DIR1, ("E1", "E2")).issues == ("direction_mismatch",)


def test_dir_ac4_speculative_and_reversed_sentence_two() -> None:
    """Given E2+E3, When S_SPEC2 is checked, Then both new codes, in ISSUES order."""
    c = CHK(S_SPEC2, ("E2", "E3"))
    assert (c.supported, c.issues, c.refs) == (
        False,
        ("direction_mismatch", "speculative"),
        ("E2", "E3"),
    )


def test_dir_ac4_speculative_alone_is_flagged() -> None:
    """Given a hedged sentence with no role conflict, Then issues == ('speculative',)."""
    c = CHK("Tài khoản A3154676584 có thể là tài khoản trung gian.", ("E1",))
    assert c.issues == ("speculative",)
    assert c.supported is False


def test_dir_ac5_correct_direction_sentences_are_supported() -> None:
    """Given sentences that state the right direction (or none), Then supported, no issues."""
    cases = [
        (S_IN, ("E2",)),
        (S_OUT, ("E1",)),
        (S_EN, ("E1",)),
        (S_TXN, ("T0000196919",)),
        (S_CHAIN, ("E3", "E2")),
        ("Tài khoản A9418747931 nhận 153,936,000 VND.", ("E1",)),
        (S_REL, ("E1",)),
        (S_CAN, ("E1",)),
        # neither account is in D1, so the direction check skips them
        ("Tài khoản A1111111111 nhận tiền từ tài khoản A2222222222.", ("E1",)),
    ]
    for text, cites in cases:
        c = CHK(text, cites)
        assert (c.supported, c.issues) == (True, ()), (text, c)


def test_dir_ac5_8c_sample_still_passes_on_ev() -> None:
    """Given S_OK1 of 8c on EV, Then (True, (), ('E1',)) as before."""
    v = validation()
    c = v.check_claim(v.Claim(str(S_OK1["text"]), tuple(S_OK1["cites"])), EV)  # type: ignore[arg-type]
    assert (c.supported, c.issues, c.refs) == (True, (), ("E1",))


def test_dir_ac6_single_account_wrong_direction_is_mismatch() -> None:
    """Given a sentence naming one account with the wrong role, Then direction_mismatch."""
    v = validation()
    wrong = [
        CHK("Tài khoản A9418747931 chuyển đi 153,936,000 VND.", ("E1",)),
        v.check_claim(
            v.Claim("Tài khoản A01 chuyển 390,000,000 VND tiền mặt vào ngày 2026-03-02.", ("E1",)),
            EV,
        ),
        CHK("Tiền được gửi từ A9418747931 tới A3154676584.", ("E1",)),
        CHK("Khách hàng nhận 153,936,000 VND từ tài khoản A9418747931.", ("E4",)),
    ]
    for c in wrong:
        assert c.issues == ("direction_mismatch",), c


def test_dir_ac6_counterparty_out_item_confirms_dst() -> None:
    """Given the OUT counterparty item D4, When the customer sends to A941, Then no issue."""
    c = CHK("Khách hàng chuyển 153,936,000 VND cho tài khoản A9418747931.", ("E4",))
    assert c.issues == ()
