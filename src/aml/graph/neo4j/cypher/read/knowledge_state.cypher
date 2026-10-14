// The single bookkeeping node of the knowledge layer; no row means it was never built.
MATCH (s:KnowledgeState {name: 'knowledge'})
RETURN s.build_id AS build_id, s.built_at AS built_at, s.embed_model AS embed_model,
       s.dimensions AS dimensions, s.corpus_sha256 AS corpus_sha256, s.case_run_id AS case_run_id,
       s.source_backend AS source_backend, s.version AS version;
