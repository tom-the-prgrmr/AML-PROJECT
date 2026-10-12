// The single bookkeeping node of the projection; no row means it was never synced.
MATCH (s:SyncState {name: 'projection'})
RETURN s.txn_watermark AS txn_watermark, s.source_backend AS source_backend,
       s.er_run_id AS er_run_id, s.last_run_id AS last_run_id, s.updated_at AS updated_at;
