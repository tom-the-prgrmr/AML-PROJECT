// Bookkeeping node, written last: a failed build leaves it (and so the next build_id) untouched.
MERGE (s:KnowledgeState {name: 'knowledge'})
SET s.build_id = $build_id, s.built_at = datetime(), s.embed_model = $embed_model,
    s.dimensions = $dimensions, s.corpus_sha256 = $corpus_sha256, s.case_run_id = $case_run_id,
    s.source_backend = $source_backend, s.version = $version;
