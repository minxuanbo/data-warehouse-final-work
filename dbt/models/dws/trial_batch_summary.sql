select b.batch_id,b.source,b.scope_version,b.coverage_status,b.acceptance_status,
       b.source_revision,cast(case when b.acceptance_status='accepted' then N'采集技术验收通过，联调中' else N'采集待验收，联调中' end as nvarchar(50)) as dataset_status,
       count_big(o.observation_key) as source_posting_count,
       sum(cast(o.body_valid as bigint)) as body_valid_count,
       sum(case when o.education_raw is null then cast(1 as bigint) else 0 end) as education_missing_count,
       sum(case when o.category_raw is null then cast(1 as bigint) else 0 end) as category_missing_count
from {{ source('audit','collection_batch') }} b
join {{ source('dwd','fact_posting_observation') }} o on o.batch_id=b.batch_id
where b.load_mode='trial'
group by b.batch_id,b.source,b.scope_version,b.coverage_status,b.acceptance_status,b.source_revision
