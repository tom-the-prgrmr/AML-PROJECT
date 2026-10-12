// Constraints and indexes of the Neo4j projection (idempotent). Unique constraints also index the key.
CREATE CONSTRAINT customer_id_unique IF NOT EXISTS
FOR (n:Customer) REQUIRE n.golden_customer_id IS UNIQUE;

CREATE CONSTRAINT account_id_unique IF NOT EXISTS
FOR (n:Account) REQUIRE n.account_id IS UNIQUE;

CREATE CONSTRAINT device_key_unique IF NOT EXISTS
FOR (n:Device) REQUIRE n.key IS UNIQUE;

CREATE CONSTRAINT phone_key_unique IF NOT EXISTS
FOR (n:Phone) REQUIRE n.key IS UNIQUE;

CREATE CONSTRAINT address_key_unique IF NOT EXISTS
FOR (n:Address) REQUIRE n.key IS UNIQUE;

CREATE CONSTRAINT sync_state_name_unique IF NOT EXISTS
FOR (n:SyncState) REQUIRE n.name IS UNIQUE;

// One relationship per transaction id: a re-run of the sync cannot duplicate a transfer.
CREATE CONSTRAINT transfer_txn_unique IF NOT EXISTS
FOR ()-[r:TRANSFERRED_TO]-() REQUIRE r.txn_id IS UNIQUE;

CREATE INDEX transfer_ts_idx IF NOT EXISTS
FOR ()-[r:TRANSFERRED_TO]-() ON (r.ts);

CREATE INDEX sent_day_idx IF NOT EXISTS
FOR ()-[r:SENT_TO]-() ON (r.day);
