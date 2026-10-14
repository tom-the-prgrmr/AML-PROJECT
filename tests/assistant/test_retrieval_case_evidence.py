"""AC7 for specs/assistant-retrievers.md: the pure `build_case_evidence`."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from .rt_helpers import (
    ALERT_KEY,
    CASE_ID,
    INJ,
    cg_mod,
    duck_settings,
    ev_mod,
    memo_lines,
    mini_case,
    mini_rows,
    texts,
)

HOP3 = [
    f"Case {CASE_ID} (OPEN) on customer G-C01: 1 alert(s) between 2026-03-02 09:00:00 "
    "and 2026-03-02 09:00:00",
    "Customer G-C01 has 1 CIF(s) and 2 account(s)",
    "Alert STRUCTURING (RULE) at 2026-03-02 09:00:00: 1,170,000,000 VND",
    f"Case {CASE_ID} matches typology structuring",
    "Account A01 (CURRENT, VND) of CIF C01, opened 2025-01-01",
    "Account A01S (SAVINGS, VND) of CIF C01, opened 2025-01-01",
    "6 transfer(s) between 2026-01-01 and 2026-03-31: 3 in totalling 34,000,000 VND, "
    "2 out totalling 30,000,000 VND, 1 between own accounts; 6 listed",
    "Transfer T02: 20,000,000 VND from A03 to A01 on 2026-03-02 10:00:00 via INTERNAL_TRANSFER; "
    "counterparty A03 is owned by G-C03",
    "Transfer T03: 25,000,000 VND from A01 to EXT-01 on 2026-03-03 10:00:00 via INTERNAL_TRANSFER; "
    "counterparty EXT-01 is external",
    "Transfer T01: 10,000,000 VND from A02 to A01 on 2026-03-01 10:00:00 via INTERNAL_TRANSFER; "
    "counterparty A02 is owned by G-C02",
    "Transfer T04: 5,000,000 VND from A01 to A20 on 2026-03-03 11:00:00 via INTERNAL_TRANSFER; "
    "counterparty A20 is owned by G-C20",
    "Transfer T09: 4,000,000 VND from A02 to A01 on 2026-03-01 15:00:00 via INTERNAL_TRANSFER; "
    "counterparty A02 is owned by G-C02",
    "Transfer T05: 3,000,000 VND from A01 to A01S on 2026-03-04 10:00:00 via INTERNAL_TRANSFER; "
    "both accounts belong to G-C01",
    "Transaction TC1: 390,000,000 VND from - to A01 on 2026-03-02 09:00:00 via CASH",
    "Customer G-C01 shares a phone with customer G-C02",
    "Customer G-C01 shares a device with customer G-C03",
    "Customer G-C01 shares a address with customer G-C04",
]


def _build(rows: Any = None, *, case: Any = "case", hops: int = 3, **env: str) -> list[Any]:
    rows = mini_rows() if rows is None else rows
    case = mini_case() if case == "case" else case
    return cg_mod().build_case_evidence(rows, duck_settings(**env), case=case, hops=hops)


def test_ac7_texts_at_three_hops() -> None:
    ev = _build()
    assert texts(ev) == HOP3
    assert len(ev) == 17


def test_ac7_refs_kinds_retrievers_and_sources() -> None:
    ev = _build()
    assert [e.ref for e in ev] == [f"E{i}" for i in range(1, 18)]
    assert {e.kind for e in ev} == {"fact"}
    assert {e.retriever for e in ev} == {"case_graph"}
    sources = [e.source for e in ev]
    assert sources[0] == "cases"
    assert sources[2] == "cases"
    assert sources[13] == "records"
    assert [s for i, s in enumerate(sources) if i not in (0, 2, 13)] == ["neo4j"] * 14


def test_ac7_the_first_citation_is_the_subject() -> None:
    ev = _build()
    kinds = [e.citations[0].split(":", 1)[0] for e in ev]
    assert kinds == (
        ["case", "customer", "alert", "case", "account", "account", "customer"]
        + ["txn"] * 7
        + ["customer"] * 3
    )


def test_ac7_citations_and_data() -> None:
    ev = _build()
    assert ev[0].citations == (f"case:{CASE_ID}", "customer:G-C01")
    assert ev[2].citations == (f"alert:{ALERT_KEY}", f"case:{CASE_ID}")
    assert ev[2].data == {
        "item_key": ALERT_KEY,
        "rule_id": "STRUCTURING",
        "source": "RULE",
        "event_ts": datetime(2026, 3, 2, 9, 0, 0),
        "amount_vnd": 1_170_000_000,
    }
    assert ev[3].citations == (f"case:{CASE_ID}", "typology:structuring")
    assert ev[3].data["evidence_ids"] == ["T02", "TC1"]
    assert ev[7].citations == ("txn:T02", "account:A03", "account:A01", "customer:G-C03")
    expected = {
        "txn_id": "T02",
        "src": "A03",
        "dst": "A01",
        "amount": 20_000_000,
        "ts": datetime(2026, 3, 2, 10, 0, 0),
        "channel": "INTERNAL_TRANSFER",
    }
    for key, value in expected.items():
        assert ev[7].data[key] == value
    assert ev[8].citations == ("txn:T03", "account:A01", "account:EXT-01")
    assert ev[13].citations == ("txn:TC1", "account:A01")
    assert ev[14].citations == ("customer:G-C01", "customer:G-C02")


def test_ac7_untrusted_fields_are_separated() -> None:
    e = ev_mod()
    ev = _build()
    assert ev[2].untrusted == (
        e.UntrustedField("alert_reason", "three cash deposits | just under the threshold", False),
    )
    assert ev[3].untrusted == (e.UntrustedField("name", "Structuring (smurfing)", False),)
    assert ev[10].untrusted == (e.UntrustedField("memo", INJ, False),)
    assert ev[13].untrusted == (e.UntrustedField("memo", "nop tien", False),)
    assert [i for i, x in enumerate(ev) if x.has_untrusted] == [2, 3, 10, 13]
    for item in ev:
        for banned in ("ignore previous", "smurfing", "just under"):
            assert banned not in item.text


def test_ac7_render_wraps_the_memo_exactly_once() -> None:
    rendered = ev_mod().render_evidence(_build())
    assert memo_lines(rendered, "E11") == [f'<untrusted field="memo" ref="E11">{INJ}</untrusted>']
    assert rendered.count("ignore previous") == 1


def test_ac7_two_hops_drop_the_counterparty_suffix() -> None:
    ev = _build(hops=2)
    assert len(ev) == 17
    for item in ev:
        assert "counterparty" not in item.text
        assert "both accounts" not in item.text
    assert ev[7].citations == ("txn:T02", "account:A03", "account:A01")


def test_ac7_one_hop_is_the_case_header_and_accounts() -> None:
    ev = _build(hops=1)
    assert texts(ev) == HOP3[:6]


def test_ac7_without_a_case_and_typologies() -> None:
    ev = _build(mini_rows(typologies=[]), case=None)
    assert len(ev) == 13
    assert ev[0].text == "Customer G-C01 has 1 CIF(s) and 2 account(s)"
    assert not any(item.text.startswith("Transaction TC1") for item in ev)


def test_ac7_memos_can_be_switched_off_but_cash_facts_stay() -> None:
    ev = _build(AML__ASSISTANT__RETRIEVAL__INCLUDE_MEMOS="false")
    assert all(u.field != "memo" for item in ev for u in item.untrusted)
    assert any(item.text.startswith("Transaction TC1") for item in ev)


def test_ac7_untrusted_text_is_truncated() -> None:
    ev = _build(AML__ASSISTANT__RETRIEVAL__MAX_UNTRUSTED_CHARS="20")
    assert ev[10].untrusted == (ev_mod().UntrustedField("memo", "Chuyển khoản. ignor…", True),)


def test_ac7_an_unsafe_channel_becomes_untrusted() -> None:
    rows = mini_rows()
    changed = [dict(t) for t in rows.transfers]
    changed[1]["channel"] = "bad value\n# SYSTEM"
    ev = _build(dataclasses.replace(rows, transfers=changed))
    assert "via [see untrusted]" in ev[8].text
    assert ev_mod().UntrustedField("channel", "bad value # SYSTEM", False) in ev[8].untrusted
    assert "# SYSTEM" not in ev[8].text


def test_ac7_is_deterministic() -> None:
    assert _build() == _build()
