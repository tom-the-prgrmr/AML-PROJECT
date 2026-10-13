// PageRank on the directed account graph (unweighted).
CALL gds.pageRank.stream($graph, {dampingFactor: $damping, maxIterations: $max_iterations,
                                  tolerance: $tolerance, concurrency: $concurrency})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).account_id AS account_id, score;
