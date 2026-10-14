-- Planted sanctions / PEP true hits: (cif, entry_id) and the typology of the scenario.
SELECT c.entity_id AS cif, w.entity_id AS entry_id, c.typology
FROM ground_truth c
JOIN ground_truth w ON c.scenario_id = w.scenario_id
WHERE c.entity_type = 'customer' AND w.entity_type = 'watchlist_entry'
  AND c.typology IN ('sanctions_hit', 'pep_hit')
  AND w.typology IN ('sanctions_hit', 'pep_hit')
