select b.build_id,b.scope_version,b.dictionary_version,b.rule_version,b.status as build_status,
 o.batch_id,i.source,i.source_job_id,o.observation_key,o.version_key,o.title_raw,o.analysis_date,
 o.category_raw,o.education_raw,o.experience_raw,o.source_url,o.body_valid,
 e.is_core,e.scope_reason,e.additional_requirements_raw,e.location_notes_raw,
 e.location_conflict,e.experience_conflict,e.confirmed_locations_json,e.issues_json,
 e.raw_ref,e.raw_sha256,v.payload as content_json,
 c.acceptance_status,c.coverage_status,c.source_revision,
 cast('description_raw+requirements_raw' as varchar(100)) as skill_text_scope
from {{ source('audit','analysis_build') }} b
join {{ source('dwd','observation_enrichment') }} e on e.build_id=b.build_id
join {{ source('dwd','fact_posting_observation') }} o on o.observation_key=e.observation_key
join {{ source('dim','posting_identity') }} i on i.posting_key=o.posting_key
join {{ source('dim','posting_version') }} v on v.version_key=o.version_key
join {{ source('audit','collection_batch') }} c on c.batch_id=o.batch_id
where b.status='ready'
