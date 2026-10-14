SELECT COUNT(*) AS n FROM audit_log WHERE module = 'assistant' AND decision IN ('ANSWERED', 'INSUFFICIENT_EVIDENCE') AND json_extract_string(details, '$.answer_id') = $answer_id;
