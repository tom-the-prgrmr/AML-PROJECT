// Retention: drop what is older than the oldest two-sided transaction still in the source.
// Account nodes stay.
MATCH ()-[r:TRANSFERRED_TO]->()
WHERE r.ts < $min_ts
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;

MATCH ()-[r:SENT_TO]->()
WHERE r.day < $min_day
CALL (r) { DELETE r } IN TRANSACTIONS OF 10000 ROWS;
