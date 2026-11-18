-- Topic aggregates must conserve core/body populations before city/skill expansion.
with by_topic as (
 select release_id,date_key,sum(core_posting_count) as core_count,sum(skill_denominator) as body_count
 from {{ ref('release_job_structure') }} group by release_id,date_key
), by_entry as (
 select release_id,date_key,sum(core_posting_count) as core_count,sum(skill_denominator) as body_count
 from {{ ref('release_entry_profile') }} group by release_id,date_key
)
select t.release_id,t.date_key,'structure_population_mismatch' as issue
from by_topic t join {{ ref('release_daily_summary') }} d on d.release_id=t.release_id and d.date_key=t.date_key
where t.core_count<>d.core_posting_count or t.body_count<>d.skill_denominator
union all
select e.release_id,e.date_key,'entry_population_mismatch'
from by_entry e join by_topic t on t.release_id=e.release_id and t.date_key=e.date_key
where e.core_count<>t.core_count or e.body_count<>t.body_count
union all
select p.release_id,p.date_key,'skill_denominator_mismatch'
from {{ ref('release_skill_profile') }} p join {{ ref('release_job_structure') }} t
 on t.release_id=p.release_id and t.date_key=p.date_key and t.source_key=p.source_key and t.category_key=p.category_key
where p.skill_denominator<>t.skill_denominator or p.posting_count>p.skill_denominator
