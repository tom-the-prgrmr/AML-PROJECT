-- Synthetic dataset tables (Phase 1c). Loaded from Parquet by `aml load`.
CREATE TABLE IF NOT EXISTS customers (
    cif            VARCHAR(20) PRIMARY KEY,
    full_name      VARCHAR(200),
    gender         VARCHAR(1),
    dob            DATE,
    nationality    VARCHAR(2),
    occupation     VARCHAR(100),
    kyc_risk       VARCHAR(20),
    id_type        VARCHAR(20),
    id_number      VARCHAR(30),
    phone          VARCHAR(30),
    email          VARCHAR(100),
    device_id      VARCHAR(50),
    ip             VARCHAR(45),
    address_format VARCHAR(10),
    street         VARCHAR(200),
    ward           VARCHAR(100),
    district       VARCHAR(100),
    province       VARCHAR(100),
    address        VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS customer_person (
    cif        VARCHAR(20) NOT NULL,
    person_id  VARCHAR(20) NOT NULL,
    is_primary BOOLEAN,
    variations VARCHAR(500),
    PRIMARY KEY (cif, person_id)
);

CREATE TABLE IF NOT EXISTS admin_unit_mapping (
    old_ward     VARCHAR(100),
    old_district VARCHAR(100),
    old_province VARCHAR(100),
    new_ward     VARCHAR(100),
    new_province VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id   VARCHAR(20) PRIMARY KEY,
    cif          VARCHAR(20),
    account_type VARCHAR(20),
    branch_id    VARCHAR(10),
    open_date    DATE,
    currency     VARCHAR(3)
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id            VARCHAR(20) PRIMARY KEY,
    txn_ts            TIMESTAMP,
    from_account_id   VARCHAR(20),
    to_account_id     VARCHAR(20),
    amount_vnd        BIGINT,
    channel           VARCHAR(30),
    branch_id         VARCHAR(10),
    device_id         VARCHAR(50),
    ip                VARCHAR(45),
    counterparty_bank VARCHAR(100),
    counterparty_name VARCHAR(200),
    memo              VARCHAR(1000)
);

CREATE TABLE IF NOT EXISTS ground_truth (
    scenario_id   VARCHAR(30),
    typology      VARCHAR(40),
    is_suspicious BOOLEAN,
    entity_type   VARCHAR(30),
    entity_id     VARCHAR(50),
    role          VARCHAR(30),
    start_ts      TIMESTAMP,
    end_ts        TIMESTAMP,
    reason        VARCHAR(1000)
);

CREATE TABLE IF NOT EXISTS dq_labels (
    entity_type VARCHAR(30),
    entity_id   VARCHAR(50),
    defect_type VARCHAR(50),
    detail      VARCHAR(500)
);

CREATE TABLE IF NOT EXISTS watchlist (
    entry_id       VARCHAR(20) PRIMARY KEY,
    list_type      VARCHAR(20),
    primary_name   VARCHAR(200),
    name_origin    VARCHAR(10),
    dob            DATE,
    dob_year       INTEGER,
    dob_precision  VARCHAR(10),
    nationality    VARCHAR(2),
    program        VARCHAR(50),
    listed_date    DATE
);

CREATE TABLE IF NOT EXISTS watchlist_alias (
    alias_id   VARCHAR(20) PRIMARY KEY,
    entry_id   VARCHAR(20),
    alias_name VARCHAR(200),
    alias_type VARCHAR(30)
);
