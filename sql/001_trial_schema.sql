SET XACT_ABORT ON;
IF SCHEMA_ID('audit') IS NULL EXEC('CREATE SCHEMA audit');
IF SCHEMA_ID('ods') IS NULL EXEC('CREATE SCHEMA ods');
IF SCHEMA_ID('dim') IS NULL EXEC('CREATE SCHEMA dim');
IF SCHEMA_ID('dwd') IS NULL EXEC('CREATE SCHEMA dwd');
IF SCHEMA_ID('dws') IS NULL EXEC('CREATE SCHEMA dws');
IF SCHEMA_ID('ads') IS NULL EXEC('CREATE SCHEMA ads');
IF OBJECT_ID('audit.collection_batch') IS NULL
CREATE TABLE audit.collection_batch(
 batch_id varchar(128) PRIMARY KEY, source varchar(40) NOT NULL,
 scope_version varchar(128) NOT NULL, input_hash char(64) NOT NULL,
 source_revision varchar(40) NOT NULL, manifest_json nvarchar(max) NOT NULL CHECK(ISJSON(manifest_json)=1),
 coverage_status varchar(16) NOT NULL CHECK(coverage_status IN ('complete','partial','failed')),
 acceptance_status varchar(32) NOT NULL, load_mode varchar(16) NOT NULL CHECK(load_mode='trial'),
 record_count int NOT NULL CHECK(record_count>=0), loaded_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET());
IF OBJECT_ID('ods.raw_response') IS NULL
CREATE TABLE ods.raw_response(
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),
 relative_path varchar(240) NOT NULL, sha256 char(64) NOT NULL, byte_count bigint NOT NULL,
 PRIMARY KEY(batch_id,relative_path));
IF OBJECT_ID('ods.posting_record') IS NULL
CREATE TABLE ods.posting_record(
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),
 source_job_id nvarchar(200) COLLATE Latin1_General_100_BIN2 NOT NULL,
 payload nvarchar(max) NOT NULL CHECK(ISJSON(payload)=1),
 PRIMARY KEY(batch_id,source_job_id));
IF OBJECT_ID('audit.quality_issue') IS NULL
CREATE TABLE audit.quality_issue(
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),
 issue_no int NOT NULL, payload nvarchar(max) NOT NULL CHECK(ISJSON(payload)=1),
 PRIMARY KEY(batch_id,issue_no));
IF OBJECT_ID('dim.posting_identity') IS NULL
CREATE TABLE dim.posting_identity(
 posting_key bigint IDENTITY PRIMARY KEY, source varchar(40) NOT NULL,
 source_job_id nvarchar(200) COLLATE Latin1_General_100_BIN2 NOT NULL,
 UNIQUE(source,source_job_id));
IF OBJECT_ID('dim.posting_version') IS NULL
CREATE TABLE dim.posting_version(
 version_key bigint IDENTITY PRIMARY KEY,
 posting_key bigint NOT NULL REFERENCES dim.posting_identity(posting_key),
 content_hash char(64) NOT NULL, valid_from_observed datetimeoffset NOT NULL,
 valid_to_observed datetimeoffset NULL, payload nvarchar(max) NOT NULL CHECK(ISJSON(payload)=1),
 UNIQUE(version_key,posting_key), UNIQUE(posting_key,valid_from_observed),
 CHECK(valid_to_observed IS NULL OR valid_to_observed>valid_from_observed));
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ux_posting_current' AND object_id=OBJECT_ID('dim.posting_version'))
CREATE UNIQUE INDEX ux_posting_current ON dim.posting_version(posting_key) WHERE valid_to_observed IS NULL;
IF OBJECT_ID('dwd.fact_posting_observation') IS NULL
CREATE TABLE dwd.fact_posting_observation(
 observation_key bigint IDENTITY PRIMARY KEY,
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),
 posting_key bigint NOT NULL, version_key bigint NOT NULL,
 observed_at datetimeoffset NOT NULL, analysis_date date NOT NULL,
 title_raw nvarchar(1000) NOT NULL, company_raw nvarchar(500) NOT NULL,
 category_raw nvarchar(500) NULL, experience_raw nvarchar(500) NULL,
 education_raw nvarchar(500) NULL, employment_type_raw nvarchar(500) NULL,
 source_url nvarchar(2048) NOT NULL, body_valid bit NOT NULL,
 UNIQUE(batch_id,posting_key),
 FOREIGN KEY(version_key,posting_key) REFERENCES dim.posting_version(version_key,posting_key));
IF OBJECT_ID('dim.location') IS NULL
CREATE TABLE dim.location(
 location_key bigint IDENTITY PRIMARY KEY,
 location_raw nvarchar(200) COLLATE Latin1_General_100_BIN2 NOT NULL UNIQUE);
IF OBJECT_ID('dwd.bridge_version_location') IS NULL
CREATE TABLE dwd.bridge_version_location(
 version_key bigint NOT NULL REFERENCES dim.posting_version(version_key),
 location_key bigint NOT NULL REFERENCES dim.location(location_key),
 normalization_version varchar(32) NOT NULL,
 PRIMARY KEY(version_key,location_key,normalization_version));
