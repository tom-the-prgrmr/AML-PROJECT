UNWIND $rows AS row
MATCH (a:Typology {typology_id: row.source})
MATCH (b:Procedure {procedure_id: row.target})
MERGE (a)-[r:INVESTIGATED_BY]->(b)
SET r.build_id = $build_id;
