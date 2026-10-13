// Weakly connected components of the account graph.
CALL gds.wcc.stream($graph, {concurrency: $concurrency})
YIELD nodeId, componentId
RETURN gds.util.asNode(nodeId).account_id AS account_id, componentId AS component;
