IF COL_LENGTH('audit.analysis_build','body_hash_version') IS NULL
ALTER TABLE audit.analysis_build ADD body_hash_version varchar(40) NOT NULL
 CONSTRAINT df_analysis_body_version DEFAULT 'skills-body-1.0' WITH VALUES;
IF COL_LENGTH('audit.analysis_build','skill_text_scope') IS NULL
ALTER TABLE audit.analysis_build ADD skill_text_scope varchar(200) NOT NULL
 CONSTRAINT df_analysis_text_scope DEFAULT 'description_raw+requirements_raw' WITH VALUES;
IF COL_LENGTH('dwd.observation_enrichment','education_conflict') IS NULL
ALTER TABLE dwd.observation_enrichment ADD education_conflict bit NOT NULL
 CONSTRAINT df_enrichment_education DEFAULT 0 WITH VALUES;
IF COL_LENGTH('dwd.observation_enrichment','experience_hint') IS NULL
ALTER TABLE dwd.observation_enrichment ADD experience_hint bit NOT NULL
 CONSTRAINT df_enrichment_experience_hint DEFAULT 0 WITH VALUES;
IF OBJECT_ID('audit.analysis_selection') IS NULL
CREATE TABLE audit.analysis_selection(
 batch_id varchar(128) PRIMARY KEY REFERENCES audit.collection_batch(batch_id),
 build_id bigint NOT NULL UNIQUE REFERENCES audit.analysis_build(build_id));
