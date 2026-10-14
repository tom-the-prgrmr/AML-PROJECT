-- The best-ranked hits of a scoring run with their (unchanged) Tier 2 decision;
-- {score_run_id} and {top} are replaced by integers.
SELECT s.score_rank, s.score, s.cif, s.entry_id, c.decision, s.top_features
FROM screening_ml_scores s
JOIN screening_current c
  ON c.run_id = s.result_run_id AND c.cif = s.cif AND c.entry_id = s.entry_id
WHERE s.score_run_id = {score_run_id} AND s.score_rank <= {top}
ORDER BY s.score_rank
