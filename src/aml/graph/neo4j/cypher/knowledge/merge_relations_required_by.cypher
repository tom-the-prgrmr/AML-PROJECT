UNWIND $rows AS row
MATCH (a:Procedure {procedure_id: row.source})
MATCH (b:Regulation {regulation_id: row.target})
MERGE (a)-[r:REQUIRED_BY]->(b)
SET r.build_id = $build_id;
