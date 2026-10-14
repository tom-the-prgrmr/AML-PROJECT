-- Phase 8d: memo classification. A memo label is a ranking FEATURE only: nothing here holds an
-- alert, a disposition or a case status, and no row is ever UPDATEd or DELETEd.
-- A memo is classified once per normalised key (digits become #), never per transaction.
-- memo_norm is untrusted text copied from transactions.memo: it is data for a person to read,
-- never an instruction for a model, and it is never copied into a reason or the audit trail.
CREATE TABLE IF NOT EXISTS memo_runs (
    run_id         BIGINT        PRIMARY KEY,
    run_ts         TIMESTAMP     NOT NULL,          -- UTC
    memo_version   VARCHAR(20)   NOT NULL,          -- normalisation + rules + prompt + schema
    llm_model      VARCHAR(100)  NOT NULL,
    transactions   BIGINT        NOT NULL,
    with_memo      BIGINT        NOT NULL,          -- transactions whose memo is not empty
    distinct_memos BIGINT        NOT NULL,          -- distinct raw memos
    memo_keys      BIGINT        NOT NULL,          -- distinct normalised keys
    reused         BIGINT        NOT NULL,          -- keys that already had a label
    by_rule        BIGINT        NOT NULL,
    by_llm         BIGINT        NOT NULL,
    fallback       BIGINT        NOT NULL,
    llm_calls      BIGINT        NOT NULL,
    keys_left      BIGINT        NOT NULL,          -- > 0: the run stopped early
    seconds        DOUBLE        NOT NULL,
    actor          VARCHAR(60)   NOT NULL
);

-- One row = one answer of the rule layer or of the model for a key.
CREATE TABLE IF NOT EXISTS memo_classifications (
    run_id        BIGINT         NOT NULL,
    memo_key      VARCHAR(32)    NOT NULL,          -- first 32 hex characters of SHA-256(memo_norm)
    memo_version  VARCHAR(20)    NOT NULL,
    llm_model     VARCHAR(100)   NOT NULL,
    memo_norm     VARCHAR(4000)  NOT NULL,          -- untrusted text, for people to compare
    category      VARCHAR(30)    NOT NULL,          -- one of the six closed categories
    method        VARCHAR(10)    NOT NULL,          -- RULE | LLM | FALLBACK
    attempts      INTEGER        NOT NULL,          -- LLM calls used (RULE: 0)
    pattern       INTEGER        NOT NULL,          -- RULE: number of the pattern that matched, else 0
    transactions  BIGINT         NOT NULL,          -- transactions with this key when it was classified
    reason        VARCHAR(400)   NOT NULL,          -- built from a template, never from memo or model text
    classified_ts TIMESTAMP      NOT NULL,          -- UTC
    PRIMARY KEY (run_id, memo_key, memo_version, llm_model)
);

-- A person's label for a key. A change of mind is a new row and the row of the model above is never touched.
CREATE TABLE IF NOT EXISTS memo_overrides (
    override_id       BIGINT        PRIMARY KEY,
    memo_key          VARCHAR(32)   NOT NULL,
    memo_version      VARCHAR(20)   NOT NULL,       -- context of the decision, for tracing only
    llm_model         VARCHAR(100)  NOT NULL,
    category          VARCHAR(30)   NOT NULL,
    previous_category VARCHAR(30)   NOT NULL,       -- the label in force just before this decision
    previous_method   VARCHAR(10)   NOT NULL,
    reason            VARCHAR(500)  NOT NULL,       -- the person's own words, stored as data
    actor             VARCHAR(60)   NOT NULL,
    decided_ts        TIMESTAMP     NOT NULL        -- UTC
);

-- Six counts per case, kept apart from case_features so the Phase 7c feature set stays as it is.
CREATE TABLE IF NOT EXISTS case_memo_features (
    run_id       BIGINT        NOT NULL,            -- the case run (snapshot)
    case_id      VARCHAR(40)   NOT NULL,
    memo_version VARCHAR(20)   NOT NULL,
    llm_model    VARCHAR(100)  NOT NULL,
    labels_rev   BIGINT        NOT NULL,            -- newest override_id when the rows were written
    feature      VARCHAR(40)   NOT NULL,
    value        DOUBLE        NOT NULL,
    PRIMARY KEY (run_id, case_id, memo_version, llm_model, labels_rev, feature)
);

CREATE OR REPLACE VIEW memo_classifications_current AS
SELECT c.*
FROM memo_classifications c
WHERE c.run_id = (
    SELECT MAX(x.run_id) FROM memo_classifications x
    WHERE x.memo_key = c.memo_key AND x.memo_version = c.memo_version AND x.llm_model = c.llm_model
);

CREATE OR REPLACE VIEW memo_overrides_current AS
SELECT o.*
FROM memo_overrides o
WHERE o.override_id = (SELECT MAX(x.override_id) FROM memo_overrides x WHERE x.memo_key = o.memo_key);

-- The label in force: a person's label (HUMAN) wins over the rule or the model.
CREATE OR REPLACE VIEW memo_labels_current AS
SELECT c.memo_key,
       c.memo_version,
       c.llm_model,
       c.memo_norm,
       COALESCE(o.category, c.category)                               AS category,
       CASE WHEN o.override_id IS NULL THEN c.method ELSE 'HUMAN' END AS method,
       c.transactions,
       c.category                                                     AS model_category,
       c.method                                                       AS model_method
FROM memo_classifications_current c
LEFT JOIN memo_overrides_current o ON o.memo_key = c.memo_key;
