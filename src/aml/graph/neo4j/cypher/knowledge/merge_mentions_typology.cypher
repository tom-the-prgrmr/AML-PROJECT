UNWIND $rows AS row
MATCH (c:Chunk {chunk_id: row.chunk_id})
MATCH (e:Typology {typology_id: row.target})
MERGE (c)-[r:MENTIONS]->(e)
SET r.build_id = $build_id;
