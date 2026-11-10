select j.build_id,case when j.location_conflict=1 then N'冲突待确认'
 else coalesce(loc.value,N'未知') end as city_group,
 count_big(distinct j.observation_key) as posting_count
from {{ ref('cd_job_detail') }} j
outer apply openjson(j.confirmed_locations_json) loc
where j.is_core=1
group by j.build_id,case when j.location_conflict=1 then N'冲突待确认' else coalesce(loc.value,N'未知') end
