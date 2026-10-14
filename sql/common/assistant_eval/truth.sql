-- Phase 8e golden set: the ground-truth rows of the scenarios a question can be asked about
-- (four suspicious typologies and the planted injection memos). Read-only; ordering is done in Python.
SELECT scenario_id, typology, entity_type, entity_id, role, start_ts
FROM ground_truth
WHERE typology IN ('structuring', 'rapid_movement', 'round_tripping', 'mule_ring', 'prompt_injection');
