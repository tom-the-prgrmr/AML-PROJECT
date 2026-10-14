UNWIND $rows AS row
MERGE (e:RedFlag {red_flag_id: row.id})
SET e.name = row.name, e.doc_id = row.doc_id, e.build_id = $build_id
WITH e, row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (d)-[r:DEFINES]->(e)
SET r.build_id = $build_id;
