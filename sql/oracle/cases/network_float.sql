-- Insert one network row of case_enrichment. Oracle stores a JSON number as NUMBER and
-- python-oracledb returns it as Decimal; the one fractional value (features.pagerank_ratio) is
-- set as a BINARY_DOUBLE here so it reads back as a float, like on DuckDB.
-- Binds: :run_id, :case_id, :content (JSON text), :ratio (the pagerank_ratio, may be NULL).
INSERT INTO case_enrichment (run_id, case_id, section, content)
VALUES (
  :run_id, :case_id, 'network',
  JSON_TRANSFORM(JSON(:content),
                 SET '$.features.pagerank_ratio' = JSON_SCALAR(TO_BINARY_DOUBLE(:ratio)))
)
/
