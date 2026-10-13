-- Phase 7b-supp: the good-guy list. A screening pair (CIF, watchlist entry) that an investigator
-- cleared as a false positive stays quiet until the row expires or the customer or the entry
-- changes. Append-only: a new clearance adds a row with a higher entry_no, the view reads the
-- newest row of each pair. Hibernation has no table of its own: it is computed from the
-- dispositions and the stored items on every run. No names or document numbers are stored.
CREATE TABLE IF NOT EXISTS good_guy_list (
    entry_no             BIGINT        PRIMARY KEY,
    cif                  VARCHAR(20)   NOT NULL,
    entry_id             VARCHAR(40)   NOT NULL,
    case_id              VARCHAR(40)   NOT NULL,
    disposition_id       BIGINT        NOT NULL,     -- the FALSE_POSITIVE that produced the row
    cleared_on           DATE          NOT NULL,
    expires_on           DATE          NOT NULL,
    customer_fingerprint VARCHAR(64)   NOT NULL,     -- screening_state at the time of the clearance
    entry_fingerprint    VARCHAR(64)   NOT NULL,
    actor                VARCHAR(60)   NOT NULL,
    created_ts           TIMESTAMP     NOT NULL      -- UTC
);

CREATE OR REPLACE VIEW good_guy_current AS
SELECT * FROM good_guy_list g
WHERE entry_no = (
    SELECT MAX(entry_no) FROM good_guy_list WHERE cif = g.cif AND entry_id = g.entry_id
);

-- A SUPPRESSED item belongs to no case. 160 already creates the column nullable, this step
-- relaxes databases created before the suppression phase. Running it again changes nothing.
ALTER TABLE case_alerts ALTER COLUMN case_id DROP NOT NULL;
