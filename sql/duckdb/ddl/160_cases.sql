-- Phase 7a: alerts consolidated into one case per golden customer per rolling window, with the
-- enrichment shown to the investigator and the human dispositions. Append-only: nothing here is
-- ever UPDATEd or DELETEd; a run adds rows under a new run_id and the *_current views read the
-- latest run. No names, document numbers, phones, emails, addresses, device ids or memos are stored.
CREATE TABLE IF NOT EXISTS case_runs (
    run_id       BIGINT       PRIMARY KEY,
    run_ts       TIMESTAMP    NOT NULL,             -- UTC
    as_of        DATE         NOT NULL,
    window_days  INTEGER      NOT NULL,
    items        BIGINT       NOT NULL,             -- (alert, golden customer) rows before suppression
    alerts       BIGINT       NOT NULL,             -- distinct item_key
    suppressed   BIGINT       NOT NULL,
    active       BIGINT       NOT NULL,
    cases        BIGINT       NOT NULL,
    opened       BIGINT       NOT NULL,
    reopened     BIGINT       NOT NULL,
    closed       BIGINT       NOT NULL,
    graph_source VARCHAR(10)  NOT NULL,             -- gds | networkx | none
    version      VARCHAR(20)  NOT NULL,
    config_hash  VARCHAR(16)  NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    run_id             BIGINT         NOT NULL,
    case_id            VARCHAR(40)    NOT NULL,
    golden_customer_id VARCHAR(40)    NOT NULL,
    window_start       TIMESTAMP      NOT NULL,
    first_alert_ts     TIMESTAMP      NOT NULL,
    last_alert_ts      TIMESTAMP      NOT NULL,
    alerts             BIGINT         NOT NULL,
    rule_alerts        BIGINT         NOT NULL,
    network_alerts     BIGINT         NOT NULL,
    screening_alerts   BIGINT         NOT NULL,
    sources            VARCHAR(40)    NOT NULL,     -- sorted sources joined by '+'
    status             VARCHAR(10)    NOT NULL,     -- OPEN | REOPENED | CLOSED
    reason             VARCHAR(1000)  NOT NULL,
    PRIMARY KEY (run_id, case_id)
);

CREATE TABLE IF NOT EXISTS case_alerts (
    run_id             BIGINT         NOT NULL,
    item_key           VARCHAR(200)   NOT NULL,
    golden_customer_id VARCHAR(40)    NOT NULL,
    case_id            VARCHAR(40)    NOT NULL,
    source             VARCHAR(10)    NOT NULL,     -- RULE | NETWORK | SCREENING
    rule_id            VARCHAR(40)    NOT NULL,
    alert_ref          VARCHAR(80)    NOT NULL,
    cif                VARCHAR(20)    NOT NULL,
    entry_id           VARCHAR(40),
    event_ts           TIMESTAMP      NOT NULL,
    end_ts             TIMESTAMP      NOT NULL,
    amount_vnd         BIGINT         NOT NULL,
    txn_count          BIGINT         NOT NULL,
    status             VARCHAR(10)    NOT NULL,     -- ACTIVE | SUPPRESSED
    suppression_rule   VARCHAR(40),
    suppression_reason VARCHAR(1000),
    retriggered        SMALLINT       NOT NULL,
    reason             VARCHAR(1000),
    details            JSON,
    PRIMARY KEY (run_id, item_key, golden_customer_id)
);

CREATE TABLE IF NOT EXISTS case_enrichment (
    run_id   BIGINT       NOT NULL,
    case_id  VARCHAR(40)  NOT NULL,
    section  VARCHAR(20)  NOT NULL,                 -- kyc | linked_cifs | dq_issues | ...
    content  JSON         NOT NULL,
    PRIMARY KEY (run_id, case_id, section)
);

-- Decisions of people (or SIMULATED ones in demos), never of the system.
CREATE TABLE IF NOT EXISTS case_dispositions (
    disposition_id BIGINT         PRIMARY KEY,
    case_id        VARCHAR(40)    NOT NULL,
    run_id         BIGINT         NOT NULL,         -- latest run containing the case when decided
    disposition    VARCHAR(20)    NOT NULL,         -- SUSPICIOUS | FALSE_POSITIVE
    reason         VARCHAR(1000)  NOT NULL,
    actor          VARCHAR(60)    NOT NULL,
    origin         VARCHAR(10)    NOT NULL,         -- HUMAN | SIMULATED
    decided_on     DATE           NOT NULL,
    decided_ts     TIMESTAMP      NOT NULL          -- UTC
);

CREATE OR REPLACE VIEW cases_current AS
SELECT * FROM cases WHERE run_id = (SELECT MAX(run_id) FROM case_runs);

CREATE OR REPLACE VIEW case_alerts_current AS
SELECT * FROM case_alerts WHERE run_id = (SELECT MAX(run_id) FROM case_runs);

CREATE OR REPLACE VIEW case_enrichment_current AS
SELECT * FROM case_enrichment WHERE run_id = (SELECT MAX(run_id) FROM case_runs);

CREATE OR REPLACE VIEW case_dispositions_current AS
SELECT * FROM case_dispositions d
WHERE disposition_id = (
    SELECT MAX(disposition_id) FROM case_dispositions WHERE case_id = d.case_id
);
