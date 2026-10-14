UNWIND $rows AS row
MERGE (d:Document {doc_id: row.doc_id})
SET d.title = row.title, d.doc_type = row.doc_type, d.version = row.version,
    d.effective_date = row.effective_date, d.language = row.language,
    d.source_file = row.source_file, d.sha256 = row.sha256, d.is_synthetic = true,
    d.build_id = $build_id;
