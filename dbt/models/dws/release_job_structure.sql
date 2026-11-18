-- B01: one release x day x source x standard job category, before multi-value expansion.
select f.release_id,f.date_key,f.source_key,f.category_key,
 count_big(*) as core_posting_count,
 sum(case when f.body_valid=1 then cast(1 as bigint) else 0 end) as skill_denominator,
 sum(case when exists_skill.job_key is not null then cast(1 as bigint) else 0 end) as skilled_posting_count
from {{ source('dwd','fact_job_daily') }} f
left join (
 select distinct release_id,date_key,job_key from {{ source('dwd','bridge_daily_skill') }}
) exists_skill on exists_skill.release_id=f.release_id and exists_skill.date_key=f.date_key and exists_skill.job_key=f.job_key
where f.is_core=1
group by f.release_id,f.date_key,f.source_key,f.category_key
