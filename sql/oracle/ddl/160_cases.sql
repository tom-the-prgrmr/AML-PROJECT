-- Phase 7a: alerts consolidated into one case per golden customer per rolling window, with the
-- enrichment shown to the investigator and the human dispositions. Append-only: nothing here is
-- ever UPDATEd or DELETEd; a run adds rows under a new run_id and the *_current views read the
-- latest run. No names, document numbers, phones, emails, addresses, device ids or memos are stored.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_runs (
      run_id       NUMBER(12)          NOT NULL,
      run_ts       TIMESTAMP(6)        NOT NULL,             -- UTC
      as_of        DATE                NOT NULL,
      window_days  NUMBER(6)           NOT NULL,
      items        NUMBER(18)          NOT NULL,             -- (alert, golden customer) rows before suppression
      alerts       NUMBER(18)          NOT NULL,             -- distinct item_key
      suppressed   NUMBER(18)          NOT NULL,
      active       NUMBER(18)          NOT NULL,
      cases        NUMBER(18)          NOT NULL,
      opened       NUMBER(18)          NOT NULL,
      reopened     NUMBER(18)          NOT NULL,
      closed       NUMBER(18)          NOT NULL,
      graph_source VARCHAR2(10 CHAR)   NOT NULL,             -- gds | networkx | none
      version      VARCHAR2(20 CHAR)   NOT NULL,
      config_hash  VARCHAR2(16 CHAR)   NOT NULL,
      CONSTRAINT pk_case_runs PRIMARY KEY (run_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE cases (
      run_id             NUMBER(12)          NOT NULL,
      case_id            VARCHAR2(40 CHAR)   NOT NULL,
      golden_customer_id VARCHAR2(40 CHAR)   NOT NULL,
      window_start       TIMESTAMP(6)        NOT NULL,
      first_alert_ts     TIMESTAMP(6)        NOT NULL,
      last_alert_ts      TIMESTAMP(6)        NOT NULL,
      alerts             NUMBER(18)          NOT NULL,
      rule_alerts        NUMBER(18)          NOT NULL,
      network_alerts     NUMBER(18)          NOT NULL,
      screening_alerts   NUMBER(18)          NOT NULL,
      sources            VARCHAR2(40 CHAR)   NOT NULL,       -- sorted sources joined by '+'
      status             VARCHAR2(10 CHAR)   NOT NULL,       -- OPEN | REOPENED | CLOSED
      reason             VARCHAR2(1000 CHAR) NOT NULL,
      CONSTRAINT pk_cases PRIMARY KEY (run_id, case_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_alerts (
      run_id             NUMBER(12)          NOT NULL,
      item_key           VARCHAR2(200 CHAR)  NOT NULL,
      golden_customer_id VARCHAR2(40 CHAR)   NOT NULL,
      case_id            VARCHAR2(40 CHAR)   NOT NULL,
      source             VARCHAR2(10 CHAR)   NOT NULL,       -- RULE | NETWORK | SCREENING
      rule_id            VARCHAR2(40 CHAR)   NOT NULL,
      alert_ref          VARCHAR2(80 CHAR)   NOT NULL,
      cif                VARCHAR2(20 CHAR)   NOT NULL,
      entry_id           VARCHAR2(40 CHAR),
      event_ts           TIMESTAMP(6)        NOT NULL,
      end_ts             TIMESTAMP(6)        NOT NULL,
      amount_vnd         NUMBER(18)          NOT NULL,
      txn_count          NUMBER(18)          NOT NULL,
      status             VARCHAR2(10 CHAR)   NOT NULL,       -- ACTIVE | SUPPRESSED
      suppression_rule   VARCHAR2(40 CHAR),
      suppression_reason VARCHAR2(1000 CHAR),
      retriggered        NUMBER(1)           NOT NULL,
      reason             VARCHAR2(1000 CHAR),
      details            JSON,
      CONSTRAINT pk_case_alerts PRIMARY KEY (run_id, item_key, golden_customer_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_enrichment (
      run_id   NUMBER(12)          NOT NULL,
      case_id  VARCHAR2(40 CHAR)   NOT NULL,
      section  VARCHAR2(20 CHAR)   NOT NULL,                 -- kyc | linked_cifs | dq_issues | ...
      content  JSON                NOT NULL,
      CONSTRAINT pk_case_enrichment PRIMARY KEY (run_id, case_id, section)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_dispositions (
      disposition_id NUMBER(12)          NOT NULL,
      case_id        VARCHAR2(40 CHAR)   NOT NULL,
      run_id         NUMBER(12)          NOT NULL,           -- latest run containing the case when decided
      disposition    VARCHAR2(20 CHAR)   NOT NULL,           -- SUSPICIOUS | FALSE_POSITIVE
      reason         VARCHAR2(1000 CHAR) NOT NULL,
      actor          VARCHAR2(60 CHAR)   NOT NULL,
      origin         VARCHAR2(10 CHAR)   NOT NULL,           -- HUMAN | SIMULATED
      decided_on     DATE                NOT NULL,
      decided_ts     TIMESTAMP(6)        NOT NULL,           -- UTC
      CONSTRAINT pk_case_dispositions PRIMARY KEY (disposition_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW cases_current AS
    SELECT run_id, case_id, golden_customer_id, window_start, first_alert_ts, last_alert_ts,
           alerts, rule_alerts, network_alerts, screening_alerts, sources, status, reason
    FROM cases
    WHERE run_id = (SELECT MAX(run_id) FROM case_runs)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_alerts_current AS
    SELECT run_id, item_key, golden_customer_id, case_id, source, rule_id, alert_ref, cif,
           entry_id, event_ts, end_ts, amount_vnd, txn_count, status, suppression_rule,
           suppression_reason, retriggered, reason, details
    FROM case_alerts
    WHERE run_id = (SELECT MAX(run_id) FROM case_runs)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_enrichment_current AS
    SELECT run_id, case_id, section, content
    FROM case_enrichment
    WHERE run_id = (SELECT MAX(run_id) FROM case_runs)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_dispositions_current AS
    SELECT disposition_id, case_id, run_id, disposition, reason, actor, origin, decided_on,
           decided_ts
    FROM case_dispositions d
    WHERE disposition_id = (
      SELECT MAX(disposition_id) FROM case_dispositions WHERE case_id = d.case_id
    )]';
END;
/
