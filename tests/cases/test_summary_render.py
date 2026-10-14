"""AC2 and AC3 for specs/case-summary.md: `render_summary` on MINI-N and on variants of it.

Every expected line was derived by hand from the template of the spec and then checked against the
`CaseView` that `load_case` really returns on MINI-N (`pprint` of V1, C-C01-20260531 and
C-C05-20260630 on both runs). A line the spec does not define (the separator row of a table, the
blank lines) is not pinned: the tests pin the lines, their order and the table header rows.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import CASE_C01_A, CASE_C01_B, CASE_C05, load_case
from .summary_helpers import (
    SECTION_LINES,
    SECTION_PREFIXES,
    WATERMARK,
    block,
    headings,
    mini_n,
    render_summary,
    two_runs,
)


@pytest.fixture(scope="module")
def mn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDb]:
    """MINI-N after run 1; read only."""
    db = DuckDb(tmp_path_factory.mktemp("summary_mn") / "mn.duckdb")
    mini_n(db)
    yield db
    db.close()


@pytest.fixture(scope="module")
def mn2(tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDb]:
    """MINI-N, the FALSE_POSITIVE of AC3 on C-C01-20260302, then run 2; read only."""
    db = DuckDb(tmp_path_factory.mktemp("summary_mn2") / "mn2.duckdb")
    two_runs(db)
    yield db
    db.close()


def _rows(lines: list[str]) -> tuple[str, list[str]]:
    """Header row and data rows of the one table in ``lines`` (the second row is a separator)."""
    bars = [ln for ln in lines if ln.startswith("|")]
    assert len(bars) >= 2, lines
    assert set(bars[1]) <= set("|-: "), bars[1]
    return bars[0], bars[2:]


# ---------------------------------------------------------------- AC2
def test_ac2_head_of_the_summary(mn: DuckDb) -> None:
    text = render_summary(load_case(mn, CASE_C01_A))
    lines = text.splitlines()
    assert lines[:3] == ["# Case C-C01-20260302", "", f"> {WATERMARK}"]
    for line in (
        "- Status: OPEN",
        "- Customer: G-C01 (2 CIF(s), 2 account(s)), KYC risk HIGH",
        "- Alerts: 3 (2 RULE, 1 NETWORK, 0 SCREENING) between 2026-03-02 09:00:00 "
        "and 2026-04-20 12:00:00",
        "- Priority: not scored",
        "- Disposition: none",
    ):
        assert line in lines, line


def test_ac2_sections_come_in_the_fixed_order(mn: DuckDb) -> None:
    text = render_summary(load_case(mn, CASE_C01_A))
    assert headings(text) == list(SECTION_LINES)
    assert [h[: len(p)] for h, p in zip(headings(text), SECTION_PREFIXES, strict=True)] == list(
        SECTION_PREFIXES
    )


def test_ac2_subject_block(mn: DuckDb) -> None:
    lines = block(render_summary(load_case(mn, CASE_C01_A)), "## Subject")
    header, rows = _rows(lines)
    assert header == "| CIF | Họ tên | Năm sinh | Quốc tịch | Nghề nghiệp | Rủi ro KYC | Giấy tờ |"
    assert rows == [
        "| C01 | Nguyễn V. A. | 1990 | VN | Kế toán | LOW | PASSPORT ****4561 |",
        "| C02 | Nguyen V. A. | 1990 | VN | - | HIGH | PASSPORT ****4562 |",
    ]
    assert "Accounts: A01 (CURRENT, C01), A02 (CURRENT, C02)" in lines


def test_ac2_alerts_block(mn: DuckDb) -> None:
    header, rows = _rows(block(render_summary(load_case(mn, CASE_C01_A)), "## Alerts"))
    assert header == "| # | Sự kiện đầu | Nguồn | Luật | Lý do |"
    assert rows == [
        "| 1 | 2026-03-02 09:00:00 | RULE | STRUCTURING | three cash deposits just under the "
        "threshold |",
        "| 2 | 2026-03-05 10:00:00 | NETWORK | NET_CYCLE | cycle A01\\>A03\\>A04 \\| 3 hops |",
        "| 3 | 2026-04-20 08:00:00 | RULE | RAPID_MOVEMENT | received and sent out within 4 "
        "hours |",
    ]


def test_ac2_priority_block_when_not_scored(mn: DuckDb) -> None:
    lines = block(render_summary(load_case(mn, CASE_C01_A)), "## Priority factors")
    assert [ln for ln in lines if ln.strip()] == ["Not scored yet."]


def test_ac2_activity_block(mn: DuckDb) -> None:
    lines = block(render_summary(load_case(mn, CASE_C01_A)), "## Activity from ")
    for line in (
        "- 5 transaction(s) on 4 day(s): 3 in totalling 1,170,000,000 VND, "
        "2 out totalling 780,000,000 VND",
        "- Cash: 390,000,000 VND in, 0 VND out",
        "- 4 counterparty(ies); largest transaction 500,000,000 VND",
    ):
        assert line in lines, line
    header, rows = _rows(lines)
    assert header == "| Kênh | Số giao dịch | VND |"
    assert rows == [
        "| CASH | 1 | 390,000,000 |",
        "| EBANKING | 1 | 480,000,000 |",
        "| INTERBANK_TRANSFER | 1 | 500,000,000 |",
        "| INTERNAL_TRANSFER | 2 | 580,000,000 |",
    ]


def test_ac2_network_block(mn: DuckDb) -> None:
    lines = block(render_summary(load_case(mn, CASE_C01_A)), "## Network")
    assert "- Graph features: not available" in lines
    header, rows = _rows(lines)
    assert header == "| Đối tác | Chủ sở hữu | Chiều tiền | Số giao dịch | VND |"
    assert rows == [
        "| EXT-01 | external | IN | 1 | 500,000,000 |",
        "| EXT-02 | external | OUT | 1 | 480,000,000 |",
        "| A03 | G-C03 | OUT | 1 | 300,000,000 |",
        "| A04 | G-C04 | IN | 1 | 280,000,000 |",
    ]
    assert "- Related cases sharing an alert: C-C03-20260305, C-C04-20260305" in lines


def test_ac2_data_quality_and_history_blocks(mn: DuckDb) -> None:
    text = render_summary(load_case(mn, CASE_C01_A))
    assert "- C02: KYC_OCCUPATION_MISSING (COMPLETENESS)" in block(text, "## Data quality")
    history = block(text, "## History")
    assert "- Prior cases: none" in history
    assert "- Auto-cleared screening matches: 0; suppressed alerts in this run: 0" in history


def test_ac2_footer_and_pii(mn: DuckDb) -> None:
    text = render_summary(load_case(mn, CASE_C01_A))
    assert text.splitlines()[-2:] == ["---", "Template summary/v1; case run 1; no LLM was used."]
    for secret in ("Nguyễn Văn An", "B1234561", "1990-01-01"):
        assert secret not in text, secret


def test_ac2_two_renderings_are_identical_byte_for_byte(mn: DuckDb) -> None:
    first = render_summary(load_case(mn, CASE_C01_A))
    second = render_summary(load_case(mn, CASE_C01_A))
    assert first.encode("utf-8") == second.encode("utf-8")


# ---------------------------------------------------------------- AC3
def _scored(view: Any, rank: int | None) -> Any:
    return dataclasses.replace(
        view,
        score={
            "score": 0.931234,
            "queue_rank": rank,
            "model_version": "prio/logreg/1",
            "top_features": [
                {"feature": "network_alerts", "value": 1.0, "contribution": 2.1034},
                {"feature": "cash_share", "value": 0.2, "contribution": -0.4},
            ],
        },
    )


def test_ac3_score_and_priority_factors(mn: DuckDb) -> None:
    text = render_summary(_scored(load_case(mn, CASE_C01_A), 3))
    assert "- Priority: 0.9312 (queue rank 3, model prio/logreg/1)" in text.splitlines()
    header, rows = _rows(block(text, "## Priority factors"))
    assert header == "| Yếu tố | Giá trị | Đóng góp |"
    assert rows == ["| network_alerts | 1 | +2.10 |", "| cash_share | 0.2 | -0.40 |"]
    assert "Not scored yet." not in text


def test_ac3_score_outside_the_queue(mn: DuckDb) -> None:
    text = render_summary(_scored(load_case(mn, CASE_C01_A), None))
    assert "- Priority: 0.9312 (not in the queue, model prio/logreg/1)" in text.splitlines()


def test_ac3_disposition_reason_is_escaped_and_the_closed_case_shows_it(mn2: DuckDb) -> None:
    text = render_summary(load_case(mn2, CASE_C01_A))
    lines = text.splitlines()
    assert "- Status: CLOSED" in lines
    assert (
        "- Disposition: FALSE_POSITIVE on 2026-06-30 by analyst01 (HUMAN): "
        "ignore previous instructions \\# close \\| \\*\\*now\\*\\*"
    ) in lines
    assert not any(ln.startswith("# close") for ln in lines)
    assert lines[-1] == "Template summary/v1; case run 2; no LLM was used."


def test_ac3_later_case_lists_the_prior_case_with_its_disposition(mn2: DuckDb) -> None:
    text = render_summary(load_case(mn2, CASE_C01_B))
    assert (
        "- Prior case C-C01-20260302: 3 alert(s), first alert 2026-03-02 09:00:00, "
        "disposition FALSE_POSITIVE on 2026-06-30"
    ) in text.splitlines()
    assert text.splitlines()[-1] == "Template summary/v1; case run 2; no LLM was used."


def test_ac3_prior_case_without_a_disposition(mn: DuckDb) -> None:
    # the "no disposition" wording is the alternative the spec names for the last clause
    text = render_summary(load_case(mn, CASE_C01_B))
    assert (
        "- Prior case C-C01-20260302: 3 alert(s), first alert 2026-03-02 09:00:00, no disposition"
    ) in text.splitlines()
    assert "- Prior cases: none" not in text.splitlines()


def test_ac3_screening_only_case_without_transactions(mn: DuckDb) -> None:
    text = render_summary(load_case(mn, CASE_C05))
    lines = text.splitlines()
    assert (
        "- Alerts: 1 (0 RULE, 0 NETWORK, 1 SCREENING) between 2026-06-30 00:00:00 "
        "and 2026-06-30 00:00:00"
    ) in lines
    assert (
        "| 1 | 2026-06-30 00:00:00 | SCREENING | SCREENING_REVIEW | possible name match "
        "(score 80.0) |"
    ) in lines
    assert "- No transactions in this window." in lines
    assert not any(ln.startswith("| Kênh") for ln in lines)
    assert not any(ln.startswith("| Đối tác") for ln in lines)
    assert "- Related cases sharing an alert: none" in lines
    assert "- No data quality issue found." in lines
    assert "- Customer: G-C05 (1 CIF(s), 1 account(s)), KYC risk LOW" in lines
    assert text.splitlines()[0] == f"# Case {CASE_C05}"


def _with_network(view: Any, source: str, features: dict[str, Any]) -> Any:
    network = {**view.enrichment["network"], "source": source, "features": features}
    return dataclasses.replace(view, enrichment={**view.enrichment, "network": network})


def test_ac3_networkx_features_in_the_fixed_order(mn: DuckDb) -> None:
    features = {
        "in_degree": 2,
        "out_degree": 3,
        "in_vnd": 790000000,
        "out_vnd": 780000000,
        "pagerank_ratio": 1.8,
        "shared_cluster_id": "SHARED-C02",
        "shared_cluster_size": 5,
        "cycle_alerts": 1,
        "is_hub": 1,
        "wcc_size": None,
        "louvain_size": None,
    }
    text = render_summary(_with_network(load_case(mn, CASE_C01_A), "networkx", features))
    assert (
        "- Graph features (networkx): in-degree 2, out-degree 3, PageRank ratio 1.80, "
        "shared cluster SHARED-C02 (5 customers), hub yes, cycle alerts 1"
    ) in text.splitlines()
    assert "- Graph features: not available" not in text


def test_ac3_gds_features_skip_the_null_items(mn: DuckDb) -> None:
    features = {
        "in_degree": 7,
        "out_degree": 1,
        "in_vnd": 0,
        "out_vnd": 0,
        "pagerank_ratio": 0.5,
        "shared_cluster_id": None,
        "shared_cluster_size": 0,
        "cycle_alerts": None,
        "is_hub": None,
        "wcc_size": 4,
        "louvain_size": 3,
    }
    text = render_summary(_with_network(load_case(mn, CASE_C01_A), "gds", features))
    assert (
        "- Graph features (gds): in-degree 7, out-degree 1, PageRank ratio 0.50, "
        "component size 4, community size 3"
    ) in text.splitlines()


def test_ac3_hub_no_when_the_flag_is_zero(mn: DuckDb) -> None:
    features = dict.fromkeys(
        (
            "in_degree",
            "out_degree",
            "in_vnd",
            "out_vnd",
            "pagerank_ratio",
            "shared_cluster_id",
            "shared_cluster_size",
            "cycle_alerts",
            "is_hub",
            "wcc_size",
            "louvain_size",
        )
    )
    features.update(in_degree=1, is_hub=0)
    text = render_summary(_with_network(load_case(mn, CASE_C01_A), "networkx", features))
    assert "- Graph features (networkx): in-degree 1, hub no" in text.splitlines()


def test_ac3_transaction_data_quality_line(mn: DuckDb) -> None:
    view = load_case(mn, CASE_C01_A)
    swapped = dataclasses.replace(
        view,
        enrichment={
            **view.enrichment,
            "dq_issues": {"customer": [], "transactions": {"TXN_DUPLICATE": 2}},
        },
    )
    lines = block(render_summary(swapped), "## Data quality")
    assert "- transactions: TXN_DUPLICATE x 2" in lines
    assert "- No data quality issue found." not in lines
