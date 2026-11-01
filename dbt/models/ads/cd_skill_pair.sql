select a.build_id,a.skill_name as skill_a,b.skill_name as skill_b,
 count_big(*) as posting_count,m.skill_denominator,
 cast(count_big(*) as float)/nullif(m.skill_denominator,0) as pair_share
from {{ ref('cd_eligible_job_skill') }} a
join {{ ref('cd_eligible_job_skill') }} b
 on a.build_id=b.build_id and a.observation_key=b.observation_key and a.skill_key<b.skill_key
join {{ ref('cd_scope_summary') }} m on m.build_id=a.build_id
group by a.build_id,a.skill_name,b.skill_name,m.skill_denominator
