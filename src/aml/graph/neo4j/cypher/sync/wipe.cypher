// Empty the projection in batches. Relationships go first, one type at a time, then the nodes
// one label at a time: removing nodes together with all their relationships in one big
// transaction ran out of memory on the `small` profile. Other labels are left alone.
MATCH ()-[r:SENT_TO]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:TRANSFERRED_TO]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:OWNS]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:USES_DEVICE]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:HAS_PHONE]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:LIVES_AT]->()
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Account)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Customer)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Device)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Phone)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:Address)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;

MATCH (n:SyncState)
CALL (n) { DELETE n } IN TRANSACTIONS OF 10000 ROWS;
