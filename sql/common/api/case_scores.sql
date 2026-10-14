-- Phase 9c: the current priority score of every scored case (latest scoring run).
-- Plain SQL, valid on DuckDB and Oracle; ordering is done by the caller.
SELECT case_id,
       score_run_id,
       model_version,
       score,
       queue_rank,
       top_features
FROM case_scores_current
