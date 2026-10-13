// Louvain communities of the undirected account graph.
CALL gds.louvain.stream($graph, {maxLevels: $max_levels, maxIterations: $max_iterations,
                                 tolerance: $tolerance, concurrency: $concurrency})
YIELD nodeId, communityId
RETURN gds.util.asNode(nodeId).account_id AS account_id, communityId AS community;
