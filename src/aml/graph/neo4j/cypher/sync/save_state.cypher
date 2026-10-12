// Bookkeeping node, written last: a failed run leaves it (and so the next `since`) untouched.
MERGE (s:SyncState {name: 'projection'})
SET s.txn_watermark = $watermark, s.source_backend = $source_backend, s.er_run_id = $er_run_id,
    s.last_run_id = $run_id, s.updated_at = datetime();
