// Constraints of the knowledge layer (idempotent): one unique key per node label.
// They also index the key.
CREATE CONSTRAINT kn_document_unique IF NOT EXISTS
FOR (n:Document) REQUIRE n.doc_id IS UNIQUE;

CREATE CONSTRAINT kn_chunk_unique IF NOT EXISTS
FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE;

CREATE CONSTRAINT kn_typology_unique IF NOT EXISTS
FOR (n:Typology) REQUIRE n.typology_id IS UNIQUE;

CREATE CONSTRAINT kn_red_flag_unique IF NOT EXISTS
FOR (n:RedFlag) REQUIRE n.red_flag_id IS UNIQUE;

CREATE CONSTRAINT kn_procedure_unique IF NOT EXISTS
FOR (n:Procedure) REQUIRE n.procedure_id IS UNIQUE;

CREATE CONSTRAINT kn_regulation_unique IF NOT EXISTS
FOR (n:Regulation) REQUIRE n.regulation_id IS UNIQUE;

CREATE CONSTRAINT kn_case_unique IF NOT EXISTS
FOR (n:Case) REQUIRE n.case_id IS UNIQUE;

CREATE CONSTRAINT kn_state_unique IF NOT EXISTS
FOR (n:KnowledgeState) REQUIRE n.name IS UNIQUE;
