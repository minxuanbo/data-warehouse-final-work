select o.batch_id,coalesce(l.location_raw,N'未知') as location_raw,
       count_big(distinct o.posting_key) as source_posting_count
from {{ source('dwd','fact_posting_observation') }} o
left join {{ source('dwd','bridge_version_location') }} b on b.version_key=o.version_key and b.normalization_version='raw_location_v1'
left join {{ source('dim','location') }} l on l.location_key=b.location_key
group by o.batch_id,coalesce(l.location_raw,N'未知')
