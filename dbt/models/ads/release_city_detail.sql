select b.release_id,b.date_key,b.job_key,
 concat(b.release_id,'|',b.date_key,'|',b.job_key) as snapshot_key,
 c.city_name,c.province_name,c.mapping_status
from {{ source('dwd','bridge_daily_city') }} b
join {{ source('dim','city') }} c on c.city_key=b.city_key
where {{ published_release('b.release_id') }}
