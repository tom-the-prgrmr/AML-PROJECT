// Whatever this build did not stamp is gone from the sources (a removed document, a surplus
// chunk, a case no longer in cases_current). Relationships first, then nodes. Customer nodes
// of the 6a projection are never matched.
MATCH ()-[r:PART_OF]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:NEXT]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:MENTIONS]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:DEFINES]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:HAS_RED_FLAG]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:INVESTIGATED_BY]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:GOVERNED_BY]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:REQUIRED_BY]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:MATCHES_TYPOLOGY]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:ABOUT]->()
WHERE r.build_id <> $build_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Case)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Chunk)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Document)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Typology)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:RedFlag)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Procedure)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Regulation)
WHERE n.build_id <> $build_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;
