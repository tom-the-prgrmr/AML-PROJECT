UNWIND $rows AS row
MATCH (c:Case {case_id: row.case_id})
MATCH (t:Typology {typology_id: row.typology_id})
MERGE (c)-[m:MATCHES_TYPOLOGY]->(t)
SET m.evidence_ids = row.evidence_ids, m.alert_keys = row.alert_keys, m.rule_ids = row.rule_ids,
    m.reason = row.reason, m.build_id = $build_id;
