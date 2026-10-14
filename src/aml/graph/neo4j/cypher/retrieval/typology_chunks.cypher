// For each typology in $typology_ids: the $limit chunks that mention it and are closest to the
// question vector. The score is the same cosine similarity the vector index reports.
MATCH (c:Chunk)-[:MENTIONS]->(t:Typology)
WHERE t.typology_id IN $typology_ids
WITH t, c, vector.similarity.cosine(c.embedding, $vector) AS score
ORDER BY t.typology_id, score DESC, c.chunk_id
WITH t, collect({chunk_id: c.chunk_id, text: c.text, doc_id: c.doc_id,
                 doc_version: c.doc_version, effective_date: c.effective_date,
                 score: score})[0..$limit] AS top
UNWIND top AS row
RETURN row.chunk_id AS chunk_id, row.text AS text, row.doc_id AS doc_id,
       row.doc_version AS doc_version, row.effective_date AS effective_date, row.score AS score
ORDER BY score DESC, chunk_id;
