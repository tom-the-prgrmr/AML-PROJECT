UNWIND $rows AS row
MATCH (a:Typology {typology_id: row.source})
MATCH (b:Regulation {regulation_id: row.target})
MERGE (a)-[r:GOVERNED_BY]->(b)
SET r.build_id = $build_id;
