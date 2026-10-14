UNWIND $rows AS row
MERGE (c:Chunk {chunk_id: row.chunk_id})
SET c.doc_id = row.doc_id, c.seq = row.seq, c.heading = row.heading, c.text = row.text,
    c.embedding = row.embedding, c.doc_version = row.doc_version,
    c.effective_date = row.effective_date, c.language = row.language, c.build_id = $build_id
WITH c, row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (c)-[p:PART_OF]->(d)
SET p.build_id = $build_id;
