UNWIND $rows AS row
MERGE (e:Regulation {regulation_id: row.id})
SET e.name = row.name, e.doc_id = row.doc_id, e.is_synthetic = true, e.build_id = $build_id
WITH e, row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (d)-[r:DEFINES]->(e)
SET r.build_id = $build_id;
