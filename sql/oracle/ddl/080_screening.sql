-- Phase 3b: screening runs and per-pair results. Rows are never deleted: a re-run marks the
-- previous current rows superseded_by = the new run_id. No customer names are stored (only cif).
-- MODE is a reserved word in Oracle, so the column is created quoted ("MODE"); statements that
-- write it must quote it too.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_runs (
      run_id             NUMBER(12)         PRIMARY KEY,
      run_ts             TIMESTAMP(6)       NOT NULL,             -- UTC
      "MODE"             VARCHAR2(12 CHAR)  NOT NULL,             -- FULL (3c adds INCREMENTAL)
      as_of              DATE               NOT NULL,
      customers_screened NUMBER(18)         NOT NULL,
      entries_screened   NUMBER(18)         NOT NULL,
      candidate_pairs    NUMBER(18)         NOT NULL,
      recorded           NUMBER(18)         NOT NULL,
      alerts             NUMBER(18)         NOT NULL,
      reviews            NUMBER(18)         NOT NULL,
      auto_cleared       NUMBER(18)         NOT NULL,
      superseded         NUMBER(18)         NOT NULL,
      version            VARCHAR2(40 CHAR)  NOT NULL,
      config_hash        VARCHAR2(16 CHAR)  NOT NULL
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_results (
      run_id            NUMBER(12)          NOT NULL,
      cif               VARCHAR2(20 CHAR)   NOT NULL,
      entry_id          VARCHAR2(20 CHAR)   NOT NULL,
      list_type         VARCHAR2(20 CHAR),
      matched_name      VARCHAR2(300 CHAR)  NOT NULL,
      matched_name_type VARCHAR2(20 CHAR)   NOT NULL,             -- PRIMARY | AKA | TRANSLITERATION | REORDERED
      token_set         BINARY_DOUBLE       NOT NULL,
      jaro_winkler      BINARY_DOUBLE       NOT NULL,
      fuzzy_score       BINARY_DOUBLE       NOT NULL,
      coverage          BINARY_DOUBLE       NOT NULL,
      name_score        BINARY_DOUBLE       NOT NULL,
      final_score       BINARY_DOUBLE       NOT NULL,
      dob_gap_years     NUMBER(4),                                -- NULL when a side has no usable year
      decision          VARCHAR2(15 CHAR)   NOT NULL,             -- ALERT | REVIEW | AUTO_CLEARED
      reason            VARCHAR2(500 CHAR)  NOT NULL,
      superseded_by     NUMBER(12),                               -- NULL = current row
      CONSTRAINT pk_screening_results PRIMARY KEY (run_id, cif, entry_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW screening_current AS
    SELECT run_id, cif, entry_id, list_type, matched_name, matched_name_type, token_set,
           jaro_winkler, fuzzy_score, coverage, name_score, final_score, dob_gap_years,
           decision, reason, superseded_by
    FROM screening_results
    WHERE superseded_by IS NULL]';
END;
/
