# Entity resolution design notes

`aml er` groups the CIFs that belong to one real person under a `golden_customer_id`. It only
labels: no row of `customers` is changed, merged or deleted. The contract is
`specs/entity-resolution.md`; this file explains the choices.

## Flow

1. Read `customers` and `admin_unit_mapping` through the `Database` abstraction.
2. Normalise in Python (`entity_resolution/normalize.py`): order-free name key from Phase 3a,
   10-digit phone, ID kind + number, lower-case email, address rewritten to the post-2025
   administrative units. Unusable values (future DOB, wrong ID length) become missing.
3. Score candidate pairs with Splink on a private in-memory DuckDB, also when the backend is
   Oracle. Splink has no Oracle backend, and one code path gives the same result on both.
4. Decide per pair, cluster the `MATCH` pairs, write `er_model`, `er_pairs`, `er_golden` and
   `er_runs` back to the active backend, then write `audit_log`.

## Blocking

Three rules, unioned: same phone, same ID number, same (new province, DOB).

Province alone is too coarse: after the old-to-new mapping the data has 8 provinces, which the
spec prototype measured as 1.78 million candidate pairs on `small` without adding one true pair.
Province plus DOB keeps the rule as a safety net for a duplicate that changed both phone and
document type.

CMND and CCCD numbers are unrelated in the data (and in reality, unless the old number is stored),
so the ID rule only catches an identical number.

## Model parameters

- `m` probabilities are fixed in `config.yaml` (`entity_resolution.m_probabilities`).
- `u` probabilities are estimated by Splink from random pairs, seeded by `settings.seed`.
- The prior comes from two deterministic rules (phone + DOB, ID number) and an assumed recall.
- No EM training. On this synthetic data EM degenerates: duplicates never differ on DOB or phone,
  so EM learns `m = 1.0 / 0.0` and a real duplicate that changed its phone could never be linked.

Two document types (CMND against CCCD) are "not comparable" and score 0; only two different numbers
of the same type count as evidence against a match.

## Decisions and clusters

- `match_probability >= match_threshold` (0.95): `MATCH`, used for clustering.
- `>= review_threshold` (0.50): `REVIEW`, stored and audited, never used for clustering.
- lower: counted in `blocked_pairs` only.

A wrong merge costs more than a missed one, because later phases group cases by golden customer.
Clusters are connected components over `MATCH` pairs. `golden_customer_id` is `G-` plus the
smallest CIF of the cluster, so it is deterministic and readable.

## Explainability

`er_pairs` stores, for every `MATCH` / `REVIEW` pair, the total match weight, the prior and one
weight per comparison, plus a `reason` string built from the same numbers. `er_model` stores the
`m`, `u` and weight of every comparison level of the run. The view `er_cluster_weights` aggregates
the pair weights per cluster, and `aml er --explain <golden id>` prints the pairs of one cluster.
Only `cif` and weights are stored, no names, phones or ID numbers.

Audit: one `MERGED` event per multi-CIF cluster (naming its weakest link), one `REVIEW` event per
review pair, one `ER_RUN_COMPLETED` event per run.

## Measured result

`uv run aml er --eval-out results/phase4/er_eval.csv` on the `small` profile (seed 42, DuckDB
backend, Splink 5.0.0), 2026-10-12:

| | value |
|---|---|
| customers | 5000 |
| pairs scored after blocking | 736 |
| `MATCH` / `REVIEW` pairs | 546 / 0 |
| clusters (with 2+ CIFs) | 4545 (364) |
| pairwise precision / recall | 1.00 / 1.00 (546 of 546) |
| cluster precision / recall | 1.00 / 1.00 (364 of 364) |

Read this with care: the synthetic duplicates are easier than real ones. The generator never
changes the phone digits or the DOB between the CIFs of one person, so the perfect score says the
pipeline is wired correctly, not that the model is tuned for production. The acceptance tests add
four hand-made changes (a changed phone, a namesake with the same DOB, a relative sharing phone and
address, a duplicate that moved province) to show one `REVIEW`, one wrong merge and one miss.

## Known limits

- A duplicate that changed phone, document type and province is not caught by any blocking rule.
- Two relatives sharing phone and address can be merged; `id` only separates them when both hold
  the same document type.
- Clusters are plain connected components, with no check on transitive links.
- Every run resolves all customers again; golden ids can change when the smallest CIF of a cluster
  changes.
