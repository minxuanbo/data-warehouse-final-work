select j.batch_id,j.source,
 case when j.location_conflict=1 then N'冲突待确认'
      when l.location_raw in (N'北京市',N'北京') then N'北京'
      when l.location_raw in (N'上海市',N'上海') then N'上海'
      when l.location_raw in (N'广州市',N'广州') then N'广州'
      when l.location_raw in (N'杭州市',N'杭州') then N'杭州'
      when l.location_raw in (N'深圳市',N'深圳') then N'深圳'
      else coalesce(l.location_raw,N'未知') end as city_group,
 count_big(distinct j.observation_key) as source_posting_count,
 cast('pilot_city_alias_v1' as varchar(40)) as city_rule_version
from {{ ref('dual_job_detail') }} j
left join {{ source('dwd','bridge_version_location') }} b
 on b.version_key=j.version_key and b.normalization_version='raw_location_v1'
left join {{ source('dim','location') }} l on l.location_key=b.location_key
group by j.batch_id,j.source,
 case when j.location_conflict=1 then N'冲突待确认'
      when l.location_raw in (N'北京市',N'北京') then N'北京'
      when l.location_raw in (N'上海市',N'上海') then N'上海'
      when l.location_raw in (N'广州市',N'广州') then N'广州'
      when l.location_raw in (N'杭州市',N'杭州') then N'杭州'
      when l.location_raw in (N'深圳市',N'深圳') then N'深圳'
      else coalesce(l.location_raw,N'未知') end
