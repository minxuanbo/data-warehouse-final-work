-- One row per actual violation. Publication requires zero rows for the release.
select b.release_id,'empty_release' as issue_code
from {{ source('audit','model_build') }} b
where b.status='ready' and not exists(select 1 from {{ source('dwd','fact_job_daily') }} f where f.release_id=b.release_id)
union all
select f.release_id,'observation_version_mismatch' as issue_code
from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','fact_posting_observation') }} o on o.observation_key=f.observation_key
join {{ source('dim','job') }} j on j.job_key=f.job_key
where f.representative_version_key<>o.version_key or j.posting_key<>o.posting_key
union all
select f.release_id,'missing_city' from {{ source('dwd','fact_job_daily') }} f
where not exists (select 1 from {{ source('dwd','bridge_daily_city') }} c where c.release_id=f.release_id and c.date_key=f.date_key and c.job_key=f.job_key)
union all
select f.release_id,'daily_skill_ineligible' from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','bridge_daily_skill') }} s on s.release_id=f.release_id and s.date_key=f.date_key and s.job_key=f.job_key
where f.is_core=0 or f.body_valid=0 or not exists (
 select 1 from {{ source('dwd','bridge_version_skill') }} b
 where b.build_id=f.build_id and b.version_key=f.representative_version_key and b.skill_key=s.skill_key and b.eligible_for_metric=1)
union all
select m.release_id,'count_or_denominator_error' from {{ ref('release_daily_summary') }} m
where m.skill_denominator>m.core_posting_count or m.core_posting_count>m.source_posting_count
union all
select s.release_id,'skill_count_exceeds_denominator' from {{ ref('release_skill_demand') }} s where s.posting_count>s.skill_denominator
union all
select m.release_id,'formal_incomplete_day' from {{ ref('release_daily_summary') }} m
join {{ source('audit','model_build') }} b on b.release_id=m.release_id
where b.channel='formal' and m.is_complete=0
union all
select i.release_id,'input_count_mismatch' from {{ source('audit','release_input') }} i
join {{ ref('cd_overview') }} c on c.build_id=i.build_id
left join {{ source('dwd','fact_job_daily') }} f on f.release_id=i.release_id and f.build_id=i.build_id
group by i.release_id,i.build_id,c.source_posting_count
having count_big(f.observation_key)<>c.source_posting_count
union all
select f.release_id,'qualification_resolution_mismatch'
from {{ source('dwd','fact_job_daily') }} f
join {{ source('audit','model_build') }} b on b.release_id=f.release_id
left join {{ source('dwd','job_qualification_evidence') }} q
 on q.release_id=f.release_id and q.date_key=f.date_key and q.job_key=f.job_key
join {{ source('dim','education') }} ed on ed.education_key=f.education_key
join {{ source('dim','experience') }} ex on ex.experience_key=f.experience_key
where b.normalization_version='conformed-cn-1.1' and (
 q.job_key is null or json_value(q.education_resolution_json,'$.value')<>ed.education_name
 or json_value(q.experience_resolution_json,'$.value')<>ex.experience_name)
