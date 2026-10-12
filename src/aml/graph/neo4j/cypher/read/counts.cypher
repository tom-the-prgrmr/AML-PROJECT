// Size of the projection: one row per node label / relationship type (columns: kind, name, n).
MATCH (x:Customer) WITH count(x) AS n RETURN 'node' AS kind, 'Customer' AS name, n
UNION ALL
MATCH (x:Account) WITH count(x) AS n RETURN 'node' AS kind, 'Account' AS name, n
UNION ALL
MATCH (x:Device) WITH count(x) AS n RETURN 'node' AS kind, 'Device' AS name, n
UNION ALL
MATCH (x:Phone) WITH count(x) AS n RETURN 'node' AS kind, 'Phone' AS name, n
UNION ALL
MATCH (x:Address) WITH count(x) AS n RETURN 'node' AS kind, 'Address' AS name, n
UNION ALL
MATCH ()-[x:OWNS]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'OWNS' AS name, n
UNION ALL
MATCH ()-[x:USES_DEVICE]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'USES_DEVICE' AS name, n
UNION ALL
MATCH ()-[x:HAS_PHONE]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'HAS_PHONE' AS name, n
UNION ALL
MATCH ()-[x:LIVES_AT]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'LIVES_AT' AS name, n
UNION ALL
MATCH ()-[x:TRANSFERRED_TO]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'TRANSFERRED_TO' AS name, n
UNION ALL
MATCH ()-[x:SENT_TO]->() WITH count(x) AS n RETURN 'relationship' AS kind, 'SENT_TO' AS name, n;
