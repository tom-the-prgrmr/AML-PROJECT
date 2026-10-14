UNWIND $rows AS row
MATCH (a:Typology {typology_id: row.source})
MATCH (b:RedFlag {red_flag_id: row.target})
MERGE (a)-[r:HAS_RED_FLAG]->(b)
SET r.build_id = $build_id;
