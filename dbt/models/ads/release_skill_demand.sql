select f.release_id,f.date_key,s.skill_key,s.skill_name,count_big(*) as posting_count,m.skill_denominator,
 cast(count_big(*) as float)/nullif(m.skill_denominator,0) as skill_share
from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','bridge_daily_skill') }} b on b.release_id=f.release_id and b.date_key=f.date_key and b.job_key=f.job_key
join {{ source('dim','skill') }} s on s.skill_key=b.skill_key
join {{ ref('release_daily_summary') }} m on m.release_id=f.release_id and m.date_key=f.date_key
where f.is_core=1 and f.body_valid=1 and {{ published_release('f.release_id') }}
group by f.release_id,f.date_key,s.skill_key,s.skill_name,m.skill_denominator
