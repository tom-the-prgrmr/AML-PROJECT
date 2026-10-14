"""Sentences the direction check must leave alone (review of assistant-direction-check).

Each one is a correct sentence the 8c assistant writes; a wrong role here would turn it into
"[CHƯA KIỂM CHỨNG]" on the case page. They document the limits of the word lists, not the ACs.
"""

from __future__ import annotations

import pytest

from tests.assistant.dir_helpers import A315, A941, CHK, D1, facts, roles

A01 = {"A01"}


@pytest.mark.parametrize(
    "text",
    [
        "Thông tin về tài khoản A01 như sau.",  # "về" = about, not a destination
        "Cảnh báo đề cập đến tài khoản A01.",
        "The alert refers to account A01.",
        "Account A01 is connected to the ring.",
        "Tài khoản A01 có giao dịch chuyển khoản 100 triệu VND.",  # "chuyển khoản" is a noun
        "Account A01 had 3 transfers totalling 5,000,000 VND.",
        "Tài khoản A01 của cá nhân này có giao dịch.",  # "cá nhân" folds onto "nhận"
        "Nhân viên quản lý tài khoản A01 là ông Nam.",
    ],
)
def test_dir_fp_no_role_for_mentions_about_an_account(text: str) -> None:
    """Given a sentence that only mentions A01, When roles are read, Then A01 has no role."""
    assert roles(text, A01) == {}


def test_dir_fp_cash_deposit_with_gui_is_incoming() -> None:
    """ "gửi tiền mặt" is a deposit: the account is the destination, not the sender."""
    deposit = "Tài khoản A01 gửi 390 triệu tiền mặt vào ngày 2026-03-02."
    assert roles(deposit, A01) == {"A01": {"dst"}}
    assert roles("Tài khoản A01 gửi 100 triệu cho A02.", {"A01", "A02"}) == {
        "A01": {"src"},
        "A02": {"dst"},
    }


def test_dir_fp_chuyen_ve_is_a_destination() -> None:
    """ "chuyển về A01" keeps "về" as a destination; only the bare "về" means "about"."""
    assert roles("Số tiền được chuyển về tài khoản A01 cùng ngày.", A01) == {"A01": {"dst"}}


@pytest.mark.parametrize(
    "text",
    [
        "Cơ quan có khả năng yêu cầu chứng từ.",  # can, not a hedge
        "Khách hàng không có khả năng trả nợ.",
        "Giao dịch diễn ra trong May 2026.",
    ],
)
def test_dir_fp_capability_wording_is_not_a_hedge(text: str) -> None:
    assert facts().is_speculative(text) is False


def test_dir_fp_hedge_with_la_still_flags() -> None:
    assert facts().is_speculative("Người hưởng lợi có khả năng là A01.") is True


def test_dir_fp_correct_sentence_with_noun_phrase_stays_supported() -> None:
    """Given D1 (A315 -> A941), a sentence that names A941 as receiver plus a noun "chuyển khoản"
    stays supported: the noun must not give A941 the sender role."""
    text = f"Tài khoản {A941} nhận 153,936,000 VND qua chuyển khoản từ {A315} ngày 2026-04-30."
    assert CHK(text, ("E1",), (D1,)).issues == ()
