select o.observation_key,o.batch_id,i.source,i.source_job_id,o.version_key,o.analysis_date,
 o.title_raw,o.company_raw,o.category_raw,o.education_raw,o.experience_raw,o.employment_type_raw,
 o.source_url, v.payload as content_json,b.source_revision,b.coverage_status,b.acceptance_status,
 cast(case when b.acceptance_status='accepted' then N'采集技术验收通过，联调中' else N'采集待验收，联调中' end as nvarchar(50)) as dataset_status
from {{ source('dwd','fact_posting_observation') }} o
join {{ source('dim','posting_identity') }} i on i.posting_key=o.posting_key
join {{ source('dim','posting_version') }} v on v.version_key=o.version_key
join {{ source('audit','collection_batch') }} b on b.batch_id=o.batch_id
