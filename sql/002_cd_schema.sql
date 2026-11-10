IF OBJECT_ID('audit.analysis_build') IS NULL
CREATE TABLE audit.analysis_build(
 build_id bigint IDENTITY PRIMARY KEY, input_hash char(64) NOT NULL UNIQUE,
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),
 scope_version varchar(128) NOT NULL, dictionary_version varchar(128) NOT NULL,
 rule_version varchar(128) NOT NULL, provenance_json nvarchar(max) NOT NULL CHECK(ISJSON(provenance_json)=1),
 status varchar(16) NOT NULL CHECK(status IN ('building','ready')),
 created_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET());
IF OBJECT_ID('dwd.observation_enrichment') IS NULL
CREATE TABLE dwd.observation_enrichment(
 build_id bigint NOT NULL REFERENCES audit.analysis_build(build_id),
 observation_key bigint NOT NULL REFERENCES dwd.fact_posting_observation(observation_key),
 is_core bit NOT NULL, scope_reason nvarchar(500) NOT NULL,
 additional_requirements_raw nvarchar(max) NULL, location_notes_raw nvarchar(max) NULL,
 location_conflict bit NOT NULL, experience_conflict bit NOT NULL,
 confirmed_locations_json nvarchar(max) NOT NULL CHECK(ISJSON(confirmed_locations_json)=1),
 issues_json nvarchar(max) NOT NULL CHECK(ISJSON(issues_json)=1),
 raw_ref nvarchar(240) NOT NULL, raw_sha256 char(64) NOT NULL,
 PRIMARY KEY(build_id,observation_key));
IF OBJECT_ID('dim.skill') IS NULL
CREATE TABLE dim.skill(skill_key bigint IDENTITY PRIMARY KEY,
 skill_name nvarchar(200) COLLATE Latin1_General_100_BIN2 NOT NULL UNIQUE);
IF OBJECT_ID('dwd.bridge_version_skill') IS NULL
CREATE TABLE dwd.bridge_version_skill(
 build_id bigint NOT NULL REFERENCES audit.analysis_build(build_id),
 version_key bigint NOT NULL REFERENCES dim.posting_version(version_key),
 skill_key bigint NOT NULL REFERENCES dim.skill(skill_key),
 requirement_level nvarchar(20) NOT NULL, eligible_for_metric bit NOT NULL,
 evidence_count int NOT NULL CHECK(evidence_count>0),
 evidence_json nvarchar(max) NOT NULL CHECK(ISJSON(evidence_json)=1),
 PRIMARY KEY(build_id,version_key,skill_key,requirement_level,eligible_for_metric));
IF DATABASE_PRINCIPAL_ID('dw_cd_reader') IS NULL CREATE ROLE dw_cd_reader;
GRANT SELECT ON SCHEMA::ads TO dw_cd_reader;
