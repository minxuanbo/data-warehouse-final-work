-- One release x batch-end Beijing day. Missing expected sources remain incomplete.
with expected as (
 select b.release_id,count_big(*) as expected_source_count
 from {{ source('audit','model_build') }} b cross apply openjson(b.expected_sources_json) s
 group by b.release_id
), coverage as (
 select release_id,date_key,count_big(*) as observed_source_count,
  sum(case when coverage_status='complete' and acceptance_status='accepted' then 1 else 0 end) as complete_source_count
 from {{ source('audit','release_input') }} group by release_id,date_key
), metrics as (
 select release_id,date_key,count_big(*) as source_posting_count,
  sum(cast(is_core as bigint)) as core_posting_count,
  sum(case when is_core=1 and body_valid=1 then cast(1 as bigint) else 0 end) as skill_denominator
 from {{ source('dwd','fact_job_daily') }} group by release_id,date_key
)
select m.*,e.expected_source_count,c.observed_source_count,c.complete_source_count,
 cast(case when c.complete_source_count=e.expected_source_count then 1 else 0 end as bit) as is_complete
from metrics m join expected e on e.release_id=m.release_id
join coverage c on c.release_id=m.release_id and c.date_key=m.date_key
