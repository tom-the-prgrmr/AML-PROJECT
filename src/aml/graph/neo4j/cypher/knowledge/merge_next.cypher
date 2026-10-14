UNWIND $rows AS row
MATCH (a:Chunk {chunk_id: row.chunk_id})
MATCH (b:Chunk {chunk_id: row.next_id})
MERGE (a)-[r:NEXT]->(b)
SET r.build_id = $build_id;
