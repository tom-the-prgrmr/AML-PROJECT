-- Phase 3b: screening runs and per-pair results. Rows are never deleted: a re-run marks the
-- previous current rows superseded_by = the new run_id. No customer names are stored (only cif).
CREATE TABLE IF NOT EXISTS screening_runs (
    run_id             BIGINT       PRIMARY KEY,
    run_ts             TIMESTAMP    NOT NULL,             -- UTC
    mode               VARCHAR(12)  NOT NULL,             -- FULL (3c adds INCREMENTAL)
    as_of              DATE         NOT NULL,
    customers_screened BIGINT       NOT NULL,
    entries_screened   BIGINT       NOT NULL,
    candidate_pairs    BIGINT       NOT NULL,
    recorded           BIGINT       NOT NULL,
    alerts             BIGINT       NOT NULL,
    reviews            BIGINT       NOT NULL,
    auto_cleared       BIGINT       NOT NULL,
    superseded         BIGINT       NOT NULL,
    version            VARCHAR(40)  NOT NULL,
    config_hash        VARCHAR(16)  NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_results (
    run_id            BIGINT        NOT NULL,
    cif               VARCHAR(20)   NOT NULL,
    entry_id          VARCHAR(20)   NOT NULL,
    list_type         VARCHAR(20),
    matched_name      VARCHAR(300)  NOT NULL,
    matched_name_type VARCHAR(20)   NOT NULL,             -- PRIMARY | AKA | TRANSLITERATION | REORDERED
    token_set         DOUBLE        NOT NULL,
    jaro_winkler      DOUBLE        NOT NULL,
    fuzzy_score       DOUBLE        NOT NULL,
    coverage          DOUBLE        NOT NULL,
    name_score        DOUBLE        NOT NULL,
    final_score       DOUBLE        NOT NULL,
    dob_gap_years     INTEGER,                             -- NULL when a side has no usable year
    decision          VARCHAR(15)   NOT NULL,             -- ALERT | REVIEW | AUTO_CLEARED
    reason            VARCHAR(500)  NOT NULL,
    superseded_by     BIGINT,                              -- NULL = current row
    PRIMARY KEY (run_id, cif, entry_id)
);

CREATE OR REPLACE VIEW screening_current AS
SELECT * FROM screening_results WHERE superseded_by IS NULL;
