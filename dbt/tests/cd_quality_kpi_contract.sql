with k as (select * from {{ ref('cd_quality_kpi') }})
select build_id from k
where numerator<0 or denominator<0 or numerator>denominator
 or goal_value<>1.0
 or (denominator=0 and (kpi_value is not null or status_value is not null))
 or (denominator>0 and (kpi_value is null or abs(kpi_value-cast(numerator as float)/denominator)>0.000000001
   or status_value is null or status_value<>case when numerator=denominator then 1 else -1 end))
 or trend_value is not null or trend_reason<>'no_comparable_daily_series'
union all
select build_id from k group by build_id,kpi_code having count_big(*)<>1
union all
select s.build_id from {{ ref('cd_overview') }} s
left join k on k.build_id=s.build_id
group by s.build_id having count(k.kpi_code)<>3
union all
-- Partial/failed input must never get a green completeness signal.
select build_id from k where kpi_code='collection_scope_complete'
 and ((coverage_status<>'complete' and (numerator<>0 or status_value<>-1))
   or (coverage_status='complete' and (numerator<>1 or status_value<>1)))
