// The same pairs as project_accounts.cypher, undirected (WCC and Louvain ignore direction).
// Rows are ordered so the in-memory node order (and so Louvain) does not depend on Neo4j node ids.
MATCH (cs:Customer)-[:OWNS]->(s:Account)-[r:SENT_TO]->(t:Account)<-[:OWNS]-(ct:Customer)
WHERE cs <> ct AND r.day >= $since AND r.day < $cutoff
WITH s, t, sum(r.total) AS total_vnd
ORDER BY t.account_id, s.account_id
WITH gds.graph.project($graph, s, t, {relationshipProperties: {total_vnd: total_vnd}},
       {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.graphName AS graph, g.nodeCount AS nodes, g.relationshipCount AS relationships;
