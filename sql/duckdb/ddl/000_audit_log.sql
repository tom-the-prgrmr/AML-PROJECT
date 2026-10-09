-- Append-only audit trail for every automated or human decision.
CREATE SEQUENCE IF NOT EXISTS audit_log_seq;

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id    BIGINT       DEFAULT nextval('audit_log_seq') PRIMARY KEY,
    event_ts    TIMESTAMP    NOT NULL,           -- UTC
    module      VARCHAR(40)  NOT NULL,           -- screening | er | monitoring | cases | assistant | ui ...
    entity_type VARCHAR(40)  NOT NULL,           -- customer | alert | case | question ...
    entity_id   VARCHAR(100) NOT NULL,
    decision    VARCHAR(40)  NOT NULL,           -- ALERT | REVIEW | AUTO_CLEARED | SUPPRESSED ...
    reason      VARCHAR      NOT NULL,           -- human-readable explanation
    version     VARCHAR(100),                    -- rule / model / prompt version
    actor       VARCHAR(100) NOT NULL,           -- 'system' or the user id
    details     JSON                              -- module-specific extras
);
