// Weakly connected components of the customer - shared value graph (customers only).
CALL gds.wcc.stream($graph, {concurrency: $concurrency})
YIELD nodeId, componentId
WITH gds.util.asNode(nodeId) AS n, componentId
WHERE n:Customer
RETURN n.golden_customer_id AS golden_customer_id, componentId AS component;
