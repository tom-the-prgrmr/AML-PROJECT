// A query TAIL, not a statement: neo4j-graphrag appends it to its own vector search, which
// yields `node` (a Chunk) and `score`. For each chunk it adds at most $max_linked knowledge
// nodes the chunk MENTIONS (by label, then key).
WITH node, score
WHERE score >= $min_score
OPTIONAL MATCH (node)-[:MENTIONS]->(e)
WHERE e:Typology OR e:RedFlag OR e:Procedure OR e:Regulation
WITH node, score, e, labels(e)[0] AS label,
     coalesce(e.typology_id, e.red_flag_id, e.procedure_id, e.regulation_id) AS id
ORDER BY label, id
WITH node, score,
     collect(CASE WHEN e IS NULL THEN null ELSE {label: label, id: id, name: e.name} END)
       [0..$max_linked] AS linked
RETURN node.chunk_id AS chunk_id, node.text AS text, node.doc_id AS doc_id,
       node.doc_version AS doc_version, node.effective_date AS effective_date, score, linked
ORDER BY score DESC, chunk_id;
