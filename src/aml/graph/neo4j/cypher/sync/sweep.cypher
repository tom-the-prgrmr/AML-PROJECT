// Customer side only: whatever this run did not stamp is gone from the source. Relationships
// first, then nodes (a stale node has no fresh relationship, so DETACH removes only stale ones).
MATCH (:Customer)-[r:OWNS]->()
WHERE r.synced_run <> $run_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (:Customer)-[r:USES_DEVICE]->()
WHERE r.synced_run <> $run_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (:Customer)-[r:HAS_PHONE]->()
WHERE r.synced_run <> $run_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (:Customer)-[r:LIVES_AT]->()
WHERE r.synced_run <> $run_id
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Customer)
WHERE n.synced_run <> $run_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Device)
WHERE n.synced_run <> $run_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Phone)
WHERE n.synced_run <> $run_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Address)
WHERE n.synced_run <> $run_id
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;
