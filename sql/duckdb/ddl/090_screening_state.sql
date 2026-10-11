-- Phase 3c: normalised names for the SQL screen, and the state that incremental screening needs.
CREATE TABLE IF NOT EXISTS screening_customer_name (
    cif       VARCHAR(20)   PRIMARY KEY,
    name_norm VARCHAR(300)  NOT NULL,
    name_key  VARCHAR(300)  NOT NULL      -- tokens sorted: order-free key
);

CREATE TABLE IF NOT EXISTS screening_list_name (
    entry_id  VARCHAR(20)   NOT NULL,
    name_type VARCHAR(20)   NOT NULL,     -- PRIMARY | AKA | TRANSLITERATION | REORDERED
    name_norm VARCHAR(300)  NOT NULL,
    name_key  VARCHAR(300)  NOT NULL,
    PRIMARY KEY (entry_id, name_norm)
);

-- Fingerprint of the last screening that covered each entity.
CREATE TABLE IF NOT EXISTS screening_state (
    entity_type VARCHAR(20)  NOT NULL,    -- customer | watchlist_entry
    entity_id   VARCHAR(20)  NOT NULL,
    fingerprint VARCHAR(64)  NOT NULL,    -- SHA-256 hex
    run_id      BIGINT       NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

-- IDF frozen at the last FULL run.
CREATE TABLE IF NOT EXISTS screening_token_stats (
    token    VARCHAR(100)  PRIMARY KEY,
    doc_freq BIGINT        NOT NULL,
    n_names  BIGINT        NOT NULL,
    run_id   BIGINT        NOT NULL
);
