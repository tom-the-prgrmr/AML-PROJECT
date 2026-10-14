// Empty the knowledge layer in batches: relationships first, one type at a time, then the nodes
// one label at a time, then the vector index and the constraints. Nothing of the 6a projection
// is touched except the ABOUT links, which belong to the Case nodes. Safe on an empty graph.
MATCH ()-[r:PART_OF]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:NEXT]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:MENTIONS]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:DEFINES]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:HAS_RED_FLAG]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:INVESTIGATED_BY]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:GOVERNED_BY]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:REQUIRED_BY]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:MATCHES_TYPOLOGY]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:ABOUT]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Case)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Chunk)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Document)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Typology)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:RedFlag)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Procedure)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Regulation)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:KnowledgeState)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

DROP INDEX chunk_embedding IF EXISTS;

DROP CONSTRAINT kn_document_unique IF EXISTS;

DROP CONSTRAINT kn_chunk_unique IF EXISTS;

DROP CONSTRAINT kn_typology_unique IF EXISTS;

DROP CONSTRAINT kn_red_flag_unique IF EXISTS;

DROP CONSTRAINT kn_procedure_unique IF EXISTS;

DROP CONSTRAINT kn_regulation_unique IF EXISTS;

DROP CONSTRAINT kn_case_unique IF EXISTS;

DROP CONSTRAINT kn_state_unique IF EXISTS;
