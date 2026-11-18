-- A multi-city job can occur in several groups; do not add rows into a global total.
select f.release_id,f.date_key,c.city_key,c.city_name,c.province_name,c.mapping_status,
 count_big(*) as posting_count
from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','bridge_daily_city') }} b on b.release_id=f.release_id and b.date_key=f.date_key and b.job_key=f.job_key
join {{ source('dim','city') }} c on c.city_key=b.city_key
where f.is_core=1 and {{ published_release('f.release_id') }}
group by f.release_id,f.date_key,c.city_key,c.city_name,c.province_name,c.mapping_status
