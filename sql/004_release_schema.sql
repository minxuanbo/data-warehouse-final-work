-- Additive migration. Existing batch, C/D and Power BI interfaces are preserved.
SET XACT_ABORT ON;
IF OBJECT_ID('dim.source') IS NULL
CREATE TABLE dim.source(source_key bigint IDENTITY PRIMARY KEY,source_code varchar(40) NOT NULL UNIQUE,
 source_name nvarchar(100) NOT NULL,official_url nvarchar(500) NOT NULL);
IF OBJECT_ID('dim.company') IS NULL
CREATE TABLE dim.company(company_key bigint IDENTITY PRIMARY KEY,company_name nvarchar(500) NOT NULL UNIQUE,
 identity_status varchar(40) NOT NULL DEFAULT 'source_brand_not_legal_entity');
IF OBJECT_ID('dim.job_category') IS NULL
CREATE TABLE dim.job_category(category_key bigint IDENTITY PRIMARY KEY,category_name nvarchar(100) NOT NULL,
 normalization_version varchar(64) NOT NULL,UNIQUE(normalization_version,category_name));
IF OBJECT_ID('dim.education') IS NULL
CREATE TABLE dim.education(education_key bigint IDENTITY PRIMARY KEY,education_name nvarchar(100) NOT NULL UNIQUE);
IF OBJECT_ID('dim.experience') IS NULL
CREATE TABLE dim.experience(experience_key bigint IDENTITY PRIMARY KEY,experience_name nvarchar(100) NOT NULL UNIQUE);
IF OBJECT_ID('dim.employment_type') IS NULL
CREATE TABLE dim.employment_type(employment_type_key bigint IDENTITY PRIMARY KEY,employment_type_name nvarchar(100) NOT NULL UNIQUE);
IF OBJECT_ID('dim.city') IS NULL
CREATE TABLE dim.city(city_key bigint IDENTITY PRIMARY KEY,city_code nvarchar(240) NOT NULL,
 city_name nvarchar(200) NOT NULL,province_name nvarchar(100) NOT NULL,mapping_status varchar(20) NOT NULL,
 normalization_version varchar(64) NOT NULL,UNIQUE(normalization_version,city_code));
IF OBJECT_ID('dim.calendar_date') IS NULL
CREATE TABLE dim.calendar_date(date_key int PRIMARY KEY,calendar_date date NOT NULL UNIQUE,
 calendar_year int NOT NULL,calendar_quarter int NOT NULL CHECK(calendar_quarter BETWEEN 1 AND 4),
 calendar_month int NOT NULL CHECK(calendar_month BETWEEN 1 AND 12),calendar_day int NOT NULL);
IF OBJECT_ID('dim.job') IS NULL
CREATE TABLE dim.job(job_key bigint IDENTITY PRIMARY KEY,posting_key bigint NOT NULL UNIQUE REFERENCES dim.posting_identity(posting_key),
 creation_method varchar(40) NOT NULL CHECK(creation_method='source_identity_only'));
IF OBJECT_ID('dwd.posting_job_map') IS NULL
CREATE TABLE dwd.posting_job_map(mapping_version varchar(64) NOT NULL,posting_key bigint NOT NULL REFERENCES dim.posting_identity(posting_key),
 job_key bigint NOT NULL REFERENCES dim.job(job_key),mapping_method varchar(40) NOT NULL,
 PRIMARY KEY(mapping_version,posting_key));
IF OBJECT_ID('audit.model_build') IS NULL
CREATE TABLE audit.model_build(release_id bigint IDENTITY PRIMARY KEY,input_hash char(64) NOT NULL UNIQUE,
 normalization_version varchar(64) NOT NULL,mapping_version varchar(64) NOT NULL,
 channel varchar(16) NOT NULL CHECK(channel IN ('sample','formal')),
 expected_sources_json nvarchar(max) NOT NULL CHECK(ISJSON(expected_sources_json)=1),
 status varchar(16) NOT NULL CHECK(status IN ('building','ready')),
 code_sha256 char(64) NOT NULL,created_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET());
IF OBJECT_ID('audit.release_input') IS NULL
CREATE TABLE audit.release_input(release_id bigint NOT NULL REFERENCES audit.model_build(release_id),
 build_id bigint NOT NULL REFERENCES audit.analysis_build(build_id),source_key bigint NOT NULL REFERENCES dim.source(source_key),
 batch_id varchar(128) NOT NULL REFERENCES audit.collection_batch(batch_id),date_key int NOT NULL REFERENCES dim.calendar_date(date_key),
 coverage_status varchar(16) NOT NULL,acceptance_status varchar(32) NOT NULL,
 PRIMARY KEY(release_id,build_id),UNIQUE(release_id,source_key,date_key));
IF OBJECT_ID('dwd.fact_job_daily') IS NULL
CREATE TABLE dwd.fact_job_daily(release_id bigint NOT NULL REFERENCES audit.model_build(release_id),
 date_key int NOT NULL REFERENCES dim.calendar_date(date_key),job_key bigint NOT NULL REFERENCES dim.job(job_key),
 build_id bigint NOT NULL REFERENCES audit.analysis_build(build_id),observation_key bigint NOT NULL REFERENCES dwd.fact_posting_observation(observation_key),
 representative_version_key bigint NOT NULL REFERENCES dim.posting_version(version_key),
 source_key bigint NOT NULL REFERENCES dim.source(source_key),company_key bigint NOT NULL REFERENCES dim.company(company_key),
 category_key bigint NOT NULL REFERENCES dim.job_category(category_key),education_key bigint NOT NULL REFERENCES dim.education(education_key),
 experience_key bigint NOT NULL REFERENCES dim.experience(experience_key),employment_type_key bigint NOT NULL REFERENCES dim.employment_type(employment_type_key),
 is_core bit NOT NULL,body_valid bit NOT NULL,job_count int NOT NULL DEFAULT 1 CHECK(job_count=1),
 PRIMARY KEY(release_id,date_key,job_key),UNIQUE(release_id,observation_key),
 FOREIGN KEY(release_id,build_id) REFERENCES audit.release_input(release_id,build_id));
IF OBJECT_ID('dwd.bridge_daily_city') IS NULL
CREATE TABLE dwd.bridge_daily_city(release_id bigint NOT NULL,date_key int NOT NULL,job_key bigint NOT NULL,
 city_key bigint NOT NULL REFERENCES dim.city(city_key),PRIMARY KEY(release_id,date_key,job_key,city_key),
 FOREIGN KEY(release_id,date_key,job_key) REFERENCES dwd.fact_job_daily(release_id,date_key,job_key));
IF OBJECT_ID('dwd.bridge_daily_skill') IS NULL
CREATE TABLE dwd.bridge_daily_skill(release_id bigint NOT NULL,date_key int NOT NULL,job_key bigint NOT NULL,
 skill_key bigint NOT NULL REFERENCES dim.skill(skill_key),PRIMARY KEY(release_id,date_key,job_key,skill_key),
 FOREIGN KEY(release_id,date_key,job_key) REFERENCES dwd.fact_job_daily(release_id,date_key,job_key));
IF OBJECT_ID('audit.publication_pointer') IS NULL
CREATE TABLE audit.publication_pointer(channel varchar(16) PRIMARY KEY CHECK(channel IN ('sample','formal')),
 release_id bigint NOT NULL REFERENCES audit.model_build(release_id),updated_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET());
IF OBJECT_ID('audit.publication_history') IS NULL
CREATE TABLE audit.publication_history(publication_id bigint IDENTITY PRIMARY KEY,channel varchar(16) NOT NULL,
 release_id bigint NOT NULL REFERENCES audit.model_build(release_id),previous_release_id bigint NULL,
 validation_json nvarchar(max) NOT NULL CHECK(ISJSON(validation_json)=1),published_at datetimeoffset NOT NULL DEFAULT SYSDATETIMEOFFSET());
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ix_daily_source_date' AND object_id=OBJECT_ID('dwd.fact_job_daily'))
CREATE INDEX ix_daily_source_date ON dwd.fact_job_daily(release_id,source_key,date_key) INCLUDE(is_core,body_valid,category_key);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ix_daily_skill_reverse' AND object_id=OBJECT_ID('dwd.bridge_daily_skill'))
CREATE INDEX ix_daily_skill_reverse ON dwd.bridge_daily_skill(release_id,skill_key,date_key,job_key);
