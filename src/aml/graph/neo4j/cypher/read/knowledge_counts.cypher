// Size of the knowledge layer: one row per measure (columns: name, n).
MATCH (x:Document) WITH count(x) AS n RETURN 'Document' AS name, n
UNION ALL
MATCH (x:Chunk) WITH count(x) AS n RETURN 'Chunk' AS name, n
UNION ALL
MATCH (x:Chunk) WHERE x.embedding IS NULL WITH count(x) AS n RETURN 'ChunkWithoutEmbedding' AS name, n
UNION ALL
MATCH (x:Typology) WITH count(x) AS n RETURN 'Typology' AS name, n
UNION ALL
MATCH (x:RedFlag) WITH count(x) AS n RETURN 'RedFlag' AS name, n
UNION ALL
MATCH (x:Procedure) WITH count(x) AS n RETURN 'Procedure' AS name, n
UNION ALL
MATCH (x:Regulation) WITH count(x) AS n RETURN 'Regulation' AS name, n
UNION ALL
MATCH (x:Case) WITH count(x) AS n RETURN 'Case' AS name, n
UNION ALL
MATCH (x:Case) WHERE NOT (x)-[:ABOUT]->() WITH count(x) AS n RETURN 'CaseUnlinked' AS name, n
UNION ALL
MATCH ()-[x:MATCHES_TYPOLOGY]->() WITH count(x) AS n RETURN 'MATCHES_TYPOLOGY' AS name, n;
