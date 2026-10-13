-- One row of the GDS run log; 14 positional values in column order.
INSERT INTO gds_runs (
    run_id, run_ts, as_of, source_backend, sync_run_id, txn_watermark, gds_version, accounts,
    active_accounts, wcc_components, louvain_communities, shared_clusters, seconds, params
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
