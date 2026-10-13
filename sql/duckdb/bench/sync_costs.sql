-- Phase 6c: how long the graph syncs took, newest run first ("MODE" is quoted: reserved in Oracle).
SELECT "MODE" AS sync_mode, seconds, lag_after_seconds
FROM graph_sync_runs
ORDER BY run_id DESC
