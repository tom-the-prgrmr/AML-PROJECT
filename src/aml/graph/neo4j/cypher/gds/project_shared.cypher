// In-memory graph customer - shared value, for values carried by 2..$max_customers_per_value customers.
MATCH (c:Customer)-[:USES_DEVICE|HAS_PHONE|LIVES_AT]->(v)
WITH v, collect(c) AS holders
WHERE size(holders) >= 2 AND size(holders) <= $max_customers_per_value
UNWIND holders AS c
WITH gds.graph.project($graph, c, v, {}, {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.graphName AS graph, g.nodeCount AS nodes, g.relationshipCount AS relationships;
