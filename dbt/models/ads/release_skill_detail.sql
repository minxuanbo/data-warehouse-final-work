select b.release_id,b.date_key,b.job_key,
 concat(b.release_id,'|',b.date_key,'|',b.job_key) as snapshot_key,s.skill_name
from {{ source('dwd','bridge_daily_skill') }} b
join {{ source('dim','skill') }} s on s.skill_key=b.skill_key
where {{ published_release('b.release_id') }}
