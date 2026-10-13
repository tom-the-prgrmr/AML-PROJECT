// Remove an in-memory graph (no error when it is missing).
CALL gds.graph.drop($graph, false) YIELD graphName
RETURN graphName AS graph;
