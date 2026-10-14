// Typologies the case matches (knowledge layer), with the evidence ids of each match.
MATCH (:Case {case_id: $case_id})-[m:MATCHES_TYPOLOGY]->(t:Typology)
RETURN t.typology_id AS typology_id, t.name AS name, m.evidence_ids AS evidence_ids
ORDER BY typology_id;
