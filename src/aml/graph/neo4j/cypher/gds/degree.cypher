// Degree centrality; $orientation NATURAL = out, REVERSE = in; $weight null = distinct counterparties.
CALL gds.degree.stream($graph, {orientation: $orientation, relationshipWeightProperty: $weight,
                                concurrency: $concurrency})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).account_id AS account_id, toInteger(score) AS score;
