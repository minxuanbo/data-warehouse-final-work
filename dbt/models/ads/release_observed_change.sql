-- Comparable consecutive complete days only. Same normalization/extraction versions fixed per release.
with days as (
 select m.*,d.calendar_date,
  p.date_key as previous_date_key,p.is_complete as previous_complete
 from {{ ref('release_daily_summary') }} m
 join {{ source('dim','calendar_date') }} d on d.date_key=m.date_key
 left join {{ source('dim','calendar_date') }} pd on pd.calendar_date=dateadd(day,-1,d.calendar_date)
 left join {{ ref('release_daily_summary') }} p on p.release_id=m.release_id and p.date_key=pd.date_key
)
select d.release_id,d.date_key,d.calendar_date,d.previous_date_key,
 d.source_posting_count,d.core_posting_count,d.skill_denominator,d.expected_source_count,
 d.observed_source_count,d.complete_source_count,d.is_complete,
 cast(case when d.is_complete=1 and d.previous_complete=1 then 1 else 0 end as bit) as is_comparable,
 case when d.is_complete=1 and d.previous_complete=1 then
  {{ observation_set_count(source('dwd','fact_job_daily'),'d.release_id','d.date_key','d.previous_date_key','new') }} end as newly_observed_count,
 case when d.is_complete=1 and d.previous_complete=1 then
  {{ observation_set_count(source('dwd','fact_job_daily'),'d.release_id','d.date_key','d.previous_date_key','first') }} end as first_discovered_count,
 case when d.is_complete=1 and d.previous_complete=1 then
  {{ observation_set_count(source('dwd','fact_job_daily'),'d.release_id','d.date_key','d.previous_date_key','missing_two') }} end as still_unobserved_count,
 case when d.is_complete=1 and d.previous_complete=1 then (
  select count_big(*) from {{ source('dwd','fact_job_daily') }} f
  join {{ source('dwd','fact_job_daily') }} p on p.release_id=f.release_id and p.job_key=f.job_key and p.date_key=d.previous_date_key
  join {{ source('dim','posting_version') }} fv on fv.version_key=f.representative_version_key
  join {{ source('dim','posting_version') }} pv on pv.version_key=p.representative_version_key
  where f.release_id=d.release_id and f.date_key=d.date_key and f.is_core=1 and p.is_core=1 and fv.content_hash<>pv.content_hash
 ) end as content_changed_count,
 case when d.is_complete=1 and d.previous_complete=1 then N'相邻完整观察日；新增观察不等于企业新发布'
      when d.is_complete=0 then N'当前日缺来源或扫描不完整'
      else N'无相邻完整基线；不计算变化' end as comparison_note
from days d
where {{ published_release('d.release_id') }}
