-- B02: a skill's numerator and the WHOLE category's eligible body denominator.
select f.release_id,f.date_key,f.source_key,f.category_key,b.skill_key,
 count_big(*) as posting_count,m.skill_denominator
from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','bridge_daily_skill') }} b
 on b.release_id=f.release_id and b.date_key=f.date_key and b.job_key=f.job_key
join {{ ref('release_job_structure') }} m
 on m.release_id=f.release_id and m.date_key=f.date_key and m.source_key=f.source_key and m.category_key=f.category_key
where f.is_core=1 and f.body_valid=1
group by f.release_id,f.date_key,f.source_key,f.category_key,b.skill_key,m.skill_denominator
