"""AC2 for specs/neo4j-gds.md: `build_features`, pure pandas on hand-written streams."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from .helpers import FEATURE_COLUMNS, mod

ACCOUNTS = [
    ("A05", "C05"),
    ("A04S", "C04"),
    ("A04", "C04"),
    ("A03", "C03"),
    ("A02", "C02"),
    ("A01", "C01"),
]
OWNER_OF_CIF = {"C01": "G-C01", "C02": "G-C01", "C03": "G-C03", "C04": "G-C04", "C05": "G-C05"}
IDS = ["A01", "A02", "A03", "A04", "A04S", "A05"]


def _scores(*pairs: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame(list(pairs), columns=["account_id", "score"])


def _accounts() -> pd.DataFrame:
    return pd.DataFrame(ACCOUNTS, columns=["account_id", "cif"])


def _streams(**override: pd.DataFrame) -> Any:
    base: dict[str, pd.DataFrame] = {
        "in_degree": _scores(("A01", 2), ("A02", 0), ("A03", 1)),
        "out_degree": _scores(("A01", 1), ("A02", 1), ("A03", 1)),
        "in_vnd": _scores(("A01", 30_000_000), ("A02", 0), ("A03", 5_000_000)),
        "out_vnd": _scores(("A01", 5_000_000), ("A02", 25_000_000), ("A03", 5_000_000)),
        "pagerank": _scores(("A01", 3.0), ("A02", 0.5), ("A03", 1.5)),
        "wcc": pd.DataFrame(
            [("A03", 7), ("A02", 7), ("A01", 7)], columns=["account_id", "component"]
        ),
        "louvain": pd.DataFrame(
            [("A01", 11), ("A02", 12), ("A03", 11)], columns=["account_id", "community"]
        ),
        "shared": pd.DataFrame(
            [("G-C04", 40), ("G-C01", 40)], columns=["golden_customer_id", "component"]
        ),
    }
    base.update(override)
    return mod("aml.graph.neo4j.features").GdsStreams(**base)


def _build(streams: Any) -> pd.DataFrame:
    return mod("aml.graph.neo4j.features").build_features(_accounts(), OWNER_OF_CIF, streams)


def _row(frame: pd.DataFrame, account: str) -> tuple[Any, ...]:
    values = frame[frame["account_id"] == account].iloc[0]
    out: list[Any] = []
    for column in FEATURE_COLUMNS[1:]:
        v = values[column]
        out.append(None if v is None or (not isinstance(v, str) and pd.isna(v)) else v)
    return tuple(out)


def _check(frame: pd.DataFrame, account: str, expected: tuple[Any, ...]) -> None:
    got = _row(frame, account)
    assert len(got) == len(expected)
    for column, g, e in zip(FEATURE_COLUMNS[1:], got, expected, strict=True):
        if isinstance(e, float):
            assert g == pytest.approx(e, abs=1e-9), (account, column)
        else:
            assert g == e, (account, column)
            assert (g is None) == (e is None), (account, column)


def test_ac2_columns_and_row_order() -> None:
    frame = _build(_streams())
    assert list(frame.columns) == FEATURE_COLUMNS
    assert list(frame["account_id"]) == IDS


def test_ac2_account_rows() -> None:
    frame = _build(_streams())
    _check(
        frame, "A01", (2, 1, 30_000_000, 5_000_000, 0.6, 1.8, "A01", 3, "A01", 2, "SHARED-C01", 2)
    )
    _check(frame, "A02", (0, 1, 0, 25_000_000, 0.1, 0.3, "A01", 3, "A02", 1, "SHARED-C01", 2))
    _check(frame, "A03", (1, 1, 5_000_000, 5_000_000, 0.3, 0.9, "A01", 3, "A01", 2, None, 0))
    _check(frame, "A04", (0, 0, 0, 0, 0.0, 0.0, None, 0, None, 0, "SHARED-C01", 2))
    _check(frame, "A04S", (0, 0, 0, 0, 0.0, 0.0, None, 0, None, 0, "SHARED-C01", 2))
    _check(frame, "A05", (0, 0, 0, 0, 0.0, 0.0, None, 0, None, 0, None, 0))
    assert frame["pagerank"].sum() == pytest.approx(1.0, abs=1e-12)


def test_ac2_column_types() -> None:
    frame = _build(_streams())
    for column in ("in_degree", "out_degree", "in_vnd", "out_vnd", "wcc_size", "louvain_size",
                   "shared_cluster_size"):  # fmt: skip
        assert str(frame[column].dtype) == "int64", column
    for column in ("pagerank", "pagerank_ratio"):
        assert str(frame[column].dtype) == "float64", column
    for column in ("wcc_id", "louvain_id", "shared_cluster_id"):
        assert frame[column].dtype == object, column
    a05 = frame[frame["account_id"] == "A05"].iloc[0]
    for column in ("wcc_id", "louvain_id", "shared_cluster_id"):
        assert a05[column] is None, column


def test_ac2_internal_gds_codes_do_not_leak() -> None:
    base = _build(_streams())
    recoded = _build(
        _streams(
            wcc=pd.DataFrame(
                [("A03", 99), ("A02", 99), ("A01", 99)], columns=["account_id", "component"]
            ),
            louvain=pd.DataFrame(
                [("A01", 12), ("A02", 11), ("A03", 12)], columns=["account_id", "community"]
            ),
        )
    )
    pd.testing.assert_frame_equal(base, recoded)


def test_ac2_empty_streams_still_give_one_row_per_account() -> None:
    scores = pd.DataFrame(columns=["account_id", "score"])
    empty = _streams(
        in_degree=scores,
        out_degree=scores,
        in_vnd=scores,
        out_vnd=scores,
        pagerank=scores,
        wcc=pd.DataFrame(columns=["account_id", "component"]),
        louvain=pd.DataFrame(columns=["account_id", "community"]),
        shared=pd.DataFrame(columns=["golden_customer_id", "component"]),
    )
    frame = _build(empty)
    assert list(frame["account_id"]) == IDS
    for account in IDS:
        _check(frame, account, (0, 0, 0, 0, 0.0, 0.0, None, 0, None, 0, None, 0))


def test_ac2_vnd_above_32_bits_stays_exact_int64() -> None:
    frame = _build(_streams(in_vnd=_scores(("A01", 5_000_000_000))))
    assert str(frame["in_vnd"].dtype) == "int64"
    assert int(frame.loc[frame["account_id"] == "A01", "in_vnd"].iloc[0]) == 5_000_000_000
