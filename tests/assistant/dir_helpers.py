"""Helpers for specs/assistant-direction-check.md: D1-D4, DEV, RD, CHK and the sample sentences.

Product names (``account_roles``, ``is_speculative``, ``transfer_sides``, the new ISSUES codes) are
reached through ``mod`` so a missing name fails the test that needs it, not the collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aml.assistant.evidence import Evidence

from .an_helpers import FakeRetriever, mod

A315 = "A3154676584"
A941 = "A9418747931"
A553 = "A5538166070"
ACC3 = {A315, A941, A553}


def _txn(ref: str, txn: str, src: str, dst: str, amount: int, ts: datetime) -> Evidence:
    text = (
        f"Transfer {txn}: {amount:,} VND from {src} to {dst} on {ts:%Y-%m-%d %H:%M:%S} "
        "via INTERNAL_TRANSFER"
    )
    return Evidence(
        ref,
        "fact",
        "case_graph",
        "neo4j",
        text,
        (f"txn:{txn}", f"account:{src}", f"account:{dst}"),
        {
            "txn_id": txn,
            "src": src,
            "dst": dst,
            "amount": amount,
            "ts": ts,
            "channel": "INTERNAL_TRANSFER",
        },
    )


D1 = _txn("E1", "T0000196919", A315, A941, 153936000, datetime(2026, 4, 30, 4, 0, 16))
D2 = _txn("E2", "T0000193641", A553, A315, 161398000, datetime(2026, 4, 28, 3, 19, 45))
D3 = _txn("E3", "T0000192133", A941, A553, 172924000, datetime(2026, 4, 27, 8, 0, 0))
D4 = Evidence(
    "E4",
    "fact",
    "case_view",
    "cases",
    "Counterparty A9418747931 (G-CIF00002986): OUT 1 transaction(s) totalling 153,936,000 VND",
    ("account:A9418747931",),
    {
        "account_id": A941,
        "owner": "G-CIF00002986",
        "direction": "OUT",
        "txns": 1,
        "vnd": 153936000,
    },
)
DEV = (D1, D2, D3, D4)


def RD() -> FakeRetriever:
    return FakeRetriever(DEV)


S_DIR1 = (
    "Tài khoản A3154676584 cũng nhận tiền từ tài khoản A9418747931 với số tiền 153,936,000 VND "
    "vào ngày 2026-04-30 04:00:16 thông qua chuyển khoản nội bộ."
)
S_DIR1_ASCII = (
    "Tai khoan A3154676584 cung nhan tien tu tai khoan A9418747931 voi so tien 153,936,000 VND."
)
S_DIR1_EN = "Account A3154676584 received 153,936,000 VND from account A9418747931 on 2026-04-30."
S_SPEC2 = (
    "Chủ sở hữu hưởng lợi cuối cùng của số tiền này có thể là A5538166070, vì họ nhận được "
    "161,398,000 VND từ A3154676584 vào ngày 2026-04-28 03:19:45 thông qua chuyển khoản "
    "INTERNAL_TRANSFER."
)
S_IN = (
    "Tài khoản A3154676584 nhận 161,398,000 VND từ tài khoản A5538166070 "
    "vào ngày 2026-04-28 03:19:45."
)
S_OUT = (
    "Tài khoản A3154676584 chuyển 153,936,000 VND cho tài khoản A9418747931 vào ngày 2026-04-30."
)
S_EN = "Account A3154676584 sent 153,936,000 VND to account A9418747931 on 2026-04-30."
S_CHAIN = (
    "Tiền đi từ tài khoản A9418747931 sang tài khoản A5538166070 rồi sang tài khoản A3154676584."
)
S_TXN = "Giao dịch T0000196919 chuyển 153,936,000 VND từ A3154676584 đến A9418747931."
S_REL = "Giao dịch T0000196919 liên quan tới tài khoản A3154676584."
S_CAN = "Investigator có thể yêu cầu chứng từ của tài khoản A3154676584."


def facts() -> Any:
    return mod("aml.assistant.facts")


def validation() -> Any:
    return mod("aml.assistant.validation")


def CHK(text: str, cites: tuple[str, ...], ev: tuple[Evidence, ...] = DEV) -> Any:
    v = validation()
    return v.check_claim(v.Claim(text, cites), ev)


def roles(text: str, accounts: set[str] = ACC3) -> dict[str, set[str]]:
    got = facts().account_roles(text, accounts)
    return {k: set(v) for k, v in got.items()}
