-- Synthetic dataset tables (Phase 1c). Loaded from Parquet by `aml load`.
-- Each table is created idempotently (ORA-00955 swallowed); statements end with '/'.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE customers (
      cif               VARCHAR2(20 CHAR) PRIMARY KEY,
      full_name         VARCHAR2(200 CHAR),
      gender            VARCHAR2(1 CHAR),
      dob               DATE,
      nationality       VARCHAR2(2 CHAR),
      occupation        VARCHAR2(100 CHAR),
      kyc_risk          VARCHAR2(20 CHAR),
      id_type           VARCHAR2(20 CHAR),
      id_number         VARCHAR2(30 CHAR),
      phone             VARCHAR2(30 CHAR),
      email             VARCHAR2(100 CHAR),
      device_id         VARCHAR2(50 CHAR),
      ip                VARCHAR2(45 CHAR),
      address_format    VARCHAR2(10 CHAR),
      street            VARCHAR2(200 CHAR),
      ward              VARCHAR2(100 CHAR),
      district          VARCHAR2(100 CHAR),
      province          VARCHAR2(100 CHAR),
      address           VARCHAR2(500 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE customer_person (
      cif               VARCHAR2(20 CHAR) NOT NULL,
      person_id         VARCHAR2(20 CHAR) NOT NULL,
      is_primary        BOOLEAN,
      variations        VARCHAR2(500 CHAR),
      PRIMARY KEY (cif, person_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE admin_unit_mapping (
      old_ward          VARCHAR2(100 CHAR),
      old_district      VARCHAR2(100 CHAR),
      old_province      VARCHAR2(100 CHAR),
      new_ward          VARCHAR2(100 CHAR),
      new_province      VARCHAR2(100 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE accounts (
      account_id        VARCHAR2(20 CHAR) PRIMARY KEY,
      cif               VARCHAR2(20 CHAR),
      account_type      VARCHAR2(20 CHAR),
      branch_id         VARCHAR2(10 CHAR),
      open_date         DATE,
      currency          VARCHAR2(3 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE transactions (
      txn_id            VARCHAR2(20 CHAR) PRIMARY KEY,
      txn_ts            TIMESTAMP(0),
      from_account_id   VARCHAR2(20 CHAR),
      to_account_id     VARCHAR2(20 CHAR),
      amount_vnd        NUMBER(18),
      channel           VARCHAR2(30 CHAR),
      branch_id         VARCHAR2(10 CHAR),
      device_id         VARCHAR2(50 CHAR),
      ip                VARCHAR2(45 CHAR),
      counterparty_bank VARCHAR2(100 CHAR),
      counterparty_name VARCHAR2(200 CHAR),
      memo              VARCHAR2(1000 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE ground_truth (
      scenario_id       VARCHAR2(30 CHAR),
      typology          VARCHAR2(40 CHAR),
      is_suspicious     BOOLEAN,
      entity_type       VARCHAR2(30 CHAR),
      entity_id         VARCHAR2(50 CHAR),
      role              VARCHAR2(30 CHAR),
      start_ts          TIMESTAMP(0),
      end_ts            TIMESTAMP(0),
      reason            VARCHAR2(1000 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dq_labels (
      entity_type       VARCHAR2(30 CHAR),
      entity_id         VARCHAR2(50 CHAR),
      defect_type       VARCHAR2(50 CHAR),
      detail            VARCHAR2(500 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE watchlist (
      entry_id          VARCHAR2(20 CHAR) PRIMARY KEY,
      list_type         VARCHAR2(20 CHAR),
      primary_name      VARCHAR2(200 CHAR),
      name_origin       VARCHAR2(10 CHAR),
      dob               DATE,
      dob_year          NUMBER(9),
      dob_precision     VARCHAR2(10 CHAR),
      nationality       VARCHAR2(2 CHAR),
      program           VARCHAR2(50 CHAR),
      listed_date       DATE
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE watchlist_alias (
      alias_id          VARCHAR2(20 CHAR) PRIMARY KEY,
      entry_id          VARCHAR2(20 CHAR),
      alias_name        VARCHAR2(200 CHAR),
      alias_type        VARCHAR2(30 CHAR)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/
