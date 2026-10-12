"""Regression: per-account features with VND totals above the 32-bit range must be storable."""

from __future__ import annotations

import pandas as pd

from aml.dba.schema import apply_schema
from aml.graph.network.runner import FEATURE_COLUMNS, _feature_rows


def test_feature_rows_with_large_vnd_after_many_small_rows_insert(duck):
    apply_schema(duck)
    n = 5000
    features = pd.DataFrame(
        {
            "account_id": [f"A{i:07d}" for i in range(n)],
            "in_degree": 0,
            "out_degree": 0,
            "in_vnd": [0] * (n - 1) + [5_000_000_000],
            "out_vnd": [0] * (n - 1) + [7_500_000_000],
            "pagerank": 1.0 / n,
            "pagerank_ratio": 1.0,
            "cycle_alerts": 0,
            "shared_cluster_id": pd.Series([None] * (n - 1) + ["SHARED-X"], dtype=object),
            "shared_cluster_size": [0] * (n - 1) + [5],
            "is_hub": 0,
        }
    )[FEATURE_COLUMNS]

    duck.insert_df("nx_account_features", _feature_rows(1, features))

    stored = duck.query_df(
        "SELECT in_vnd, out_vnd, shared_cluster_id FROM nx_account_features "
        "WHERE account_id = 'A0004999'"
    )
    assert stored.iloc[0].tolist() == [5_000_000_000, 7_500_000_000, "SHARED-X"]
    nulls = duck.query_df(
        "SELECT COUNT(*) AS n FROM nx_account_features WHERE shared_cluster_id IS NULL"
    )
    assert int(nulls["n"].iloc[0]) == n - 1
