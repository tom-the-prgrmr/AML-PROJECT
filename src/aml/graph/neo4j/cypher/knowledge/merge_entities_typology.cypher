UNWIND $rows AS row
MERGE (e:Typology {typology_id: row.id})
SET e.name = row.name, e.doc_id = row.doc_id, e.rule_ids = row.rule_ids, e.build_id = $build_id
WITH e, row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (d)-[r:DEFINES]->(e)
SET r.build_id = $build_id;
