-- Additive, release-versioned derived qualifications. Raw observations are unchanged.
IF OBJECT_ID('dwd.job_qualification_evidence') IS NULL
CREATE TABLE dwd.job_qualification_evidence(
 release_id bigint NOT NULL,date_key int NOT NULL,job_key bigint NOT NULL,
 qualification_rule_version varchar(64) NOT NULL,
 education_resolution_json nvarchar(max) NOT NULL CHECK(ISJSON(education_resolution_json)=1),
 experience_resolution_json nvarchar(max) NOT NULL CHECK(ISJSON(experience_resolution_json)=1),
 PRIMARY KEY(release_id,date_key,job_key),
 FOREIGN KEY(release_id,date_key,job_key) REFERENCES dwd.fact_job_daily(release_id,date_key,job_key));
