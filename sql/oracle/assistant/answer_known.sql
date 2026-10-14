SELECT COUNT(*) AS n FROM audit_log WHERE module = 'assistant' AND decision IN ('ANSWERED', 'INSUFFICIENT_EVIDENCE') AND JSON_VALUE(details, '$.answer_id') = :answer_id
/
