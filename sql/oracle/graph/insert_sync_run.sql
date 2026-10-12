-- One row of the sync run log; 18 positional values in column order ("MODE" is quoted: reserved).
INSERT INTO graph_sync_runs (
    run_id, run_ts, "MODE", source_backend, source_user, since_ts, watermark_from, watermark_to,
    er_run_id, nodes_sent, rels_sent, pruned, swept, lag_before_seconds, lag_after_seconds,
    seconds, in_sync, details
) VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13, :14, :15, :16, :17, :18)
/
