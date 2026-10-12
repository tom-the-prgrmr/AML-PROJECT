-- One row of the sync run log; 18 positional values in column order.
INSERT INTO graph_sync_runs (
    run_id, run_ts, mode, source_backend, source_user, since_ts, watermark_from, watermark_to,
    er_run_id, nodes_sent, rels_sent, pruned, swept, lag_before_seconds, lag_after_seconds,
    seconds, in_sync, details
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
