"""Entity resolution model: comparisons, blocking rules and Splink scoring on in-memory DuckDB.

``m`` probabilities are fixed by configuration (EM degenerates on this synthetic data, see the
spec); Splink only estimates ``u`` and the prior. Splink always runs on its own in-memory DuckDB,
whatever backend holds the results.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import duckdb
import pandas as pd
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from aml.common.config import EntityResolutionConfig

logging.getLogger("splink").setLevel(logging.ERROR)

COMPARISONS = ("name", "dob", "phone", "email", "address", "id")
BLOCKING_RULES: dict[str, tuple[str, ...]] = {
    "phone": ("phone_norm",),
    "id": ("id_norm",),
    "province_dob": ("province_new", "dob"),
}


def _rule_pairs(records: pd.DataFrame, columns: tuple[str, ...]) -> set[tuple[str, str]]:
    """All (cif_l < cif_r) pairs sharing non-null values on ``columns``."""
    pairs: set[tuple[str, str]] = set()
    for _, group in records.dropna(subset=list(columns)).groupby(list(columns)):
        cifs = sorted(group["cif"])
        pairs.update((a, b) for i, a in enumerate(cifs) for b in cifs[i + 1 :])
    return pairs


def count_blocked_pairs(records: pd.DataFrame) -> dict[str, int]:
    """Pairs produced by each blocking rule alone, plus ``total`` for their union."""
    per_rule = {name: _rule_pairs(records, cols) for name, cols in BLOCKING_RULES.items()}
    counts = {name: len(pairs) for name, pairs in per_rule.items()}
    counts["total"] = len(set().union(*per_rule.values()))
    return counts


@dataclass(frozen=True)
class Scored:
    """Splink output: every blocked pair, the clusters at the MATCH threshold and the parameters."""

    pairs: pd.DataFrame  # cif_l < cif_r, match_weight, match_probability, mw_prior, mw_<comparison>
    clusters: pd.DataFrame  # cif, cluster_id
    levels: pd.DataFrame  # comparison, level_no, label, is_null_level, m, u, weight
    prior: float  # probability two random records match


def _level(level: cll.ComparisonLevelCreator, m: float) -> cll.ComparisonLevelCreator:
    return level.configure(m_probability=m)


def build_comparisons(cfg: EntityResolutionConfig) -> list[cl.CustomComparison]:
    """The six comparisons of the spec; levels are tried in order, the first match wins."""
    m, jw = cfg.m_probabilities, cfg.name_jw_thresholds
    custom = cl.CustomComparison
    return [
        custom(
            output_column_name="name",
            comparison_levels=[
                cll.NullLevel("name_key"),
                _level(cll.ExactMatchLevel("name_key"), m["name"][0]),
                _level(cll.JaroWinklerLevel("name_key", jw[0]), m["name"][1]),
                _level(cll.JaroWinklerLevel("name_key", jw[1]), m["name"][2]),
                _level(cll.ElseLevel(), m["name"][3]),
            ],
        ),
        custom(
            output_column_name="dob",
            comparison_levels=[
                cll.NullLevel("dob"),
                _level(cll.ExactMatchLevel("dob"), m["dob"][0]),
                _level(cll.ElseLevel(), m["dob"][1]),
            ],
        ),
        custom(
            output_column_name="phone",
            comparison_levels=[
                cll.NullLevel("phone_norm"),
                _level(cll.ExactMatchLevel("phone_norm"), m["phone"][0]),
                _level(cll.ElseLevel(), m["phone"][1]),
            ],
        ),
        custom(
            output_column_name="email",
            comparison_levels=[
                cll.NullLevel("email_norm"),
                _level(cll.ExactMatchLevel("email_norm"), m["email"][0]),
                _level(cll.ElseLevel(), m["email"][1]),
            ],
        ),
        custom(
            output_column_name="address",
            comparison_levels=[
                cll.NullLevel("addr_key"),
                _level(cll.ExactMatchLevel("addr_key"), m["address"][0]),
                _level(cll.ExactMatchLevel("province_new"), m["address"][1]),
                _level(cll.ElseLevel(), m["address"][2]),
            ],
        ),
        custom(
            output_column_name="id",
            comparison_levels=[
                # CMND vs CCCD cannot be compared (unrelated numbers): no evidence either way.
                cll.CustomLevel(
                    "id_norm_l IS NULL OR id_norm_r IS NULL OR id_kind_l <> id_kind_r",
                    "ID missing or different document type",
                ).configure(is_null_level=True),
                _level(cll.ExactMatchLevel("id_norm"), m["id"][0]),
                _level(cll.ElseLevel(), m["id"][1]),
            ],
        ),
    ]


def _blocking_rules() -> list[object]:
    return [block_on(*columns) for columns in BLOCKING_RULES.values()]


def _model_levels(model: dict) -> pd.DataFrame:
    """Flatten the saved Splink model into one row per comparison level."""
    rows = []
    for comparison in model["comparisons"]:
        for number, level in enumerate(comparison["comparison_levels"]):
            m, u = level.get("m_probability"), level.get("u_probability")
            is_null = bool(level.get("is_null_level", False))
            weight = None if is_null or not m or not u else math.log2(m / u)
            rows.append(
                {
                    "comparison": comparison["output_column_name"],
                    "level_no": number,
                    "label": level.get("label_for_charts") or f"level {number}",
                    "is_null_level": is_null,
                    "m": None if is_null else m,
                    "u": None if is_null else u,
                    "weight": weight,
                }
            )
    return pd.DataFrame(rows)


def score_records(records: pd.DataFrame, cfg: EntityResolutionConfig, *, seed: int) -> Scored:
    """Estimate prior and ``u``, score every blocked pair, and cluster the MATCH pairs."""
    con = duckdb.connect(":memory:")
    try:
        linker = Linker(
            DuckDBAPI(con).register(records),
            SettingsCreator(
                link_type="dedupe_only",
                unique_id_column_name="cif",
                comparisons=build_comparisons(cfg),
                blocking_rules_to_generate_predictions=_blocking_rules(),
                retain_intermediate_calculation_columns=True,
                retain_matching_columns=False,
            ),
            log_level=logging.ERROR,
        )
        linker.training.estimate_probability_two_random_records_match(
            [block_on("phone_norm", "dob"), block_on("id_norm")],
            recall=cfg.deterministic_recall,
        )
        linker.training.estimate_u_using_random_sampling(max_pairs=cfg.u_max_pairs, seed=seed)
        model = linker.misc.save_model_to_json()
        predictions = linker.inference.predict()
        pairs = predictions.as_pandas_dataframe()
        clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(
            predictions, threshold_match_probability=cfg.match_threshold
        ).as_pandas_dataframe()
    finally:
        con.close()
    return Scored(
        pairs=_order_pairs(pairs),
        clusters=clusters[["cif", "cluster_id"]],
        levels=_model_levels(model),
        prior=float(model["probability_two_random_records_match"]),
    )


def _order_pairs(pairs: pd.DataFrame) -> pd.DataFrame:
    """Make cif_l < cif_r, sort, and derive the prior weight before any rounding."""
    pairs = pairs.copy()
    swap = pairs["cif_l"] > pairs["cif_r"]
    pairs.loc[swap, ["cif_l", "cif_r"]] = pairs.loc[swap, ["cif_r", "cif_l"]].to_numpy()
    mw_columns = [f"mw_{name}" for name in COMPARISONS]
    pairs["mw_prior"] = pairs["match_weight"] - pairs[mw_columns].sum(axis=1)
    keep = ["cif_l", "cif_r", "match_weight", "match_probability", "mw_prior", *mw_columns]
    return pairs[keep].sort_values(["cif_l", "cif_r"]).reset_index(drop=True)
