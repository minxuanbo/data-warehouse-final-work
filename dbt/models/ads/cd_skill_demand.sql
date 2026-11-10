select s.build_id,s.skill_key,s.skill_name,count_big(*) as posting_count,
 m.skill_denominator,
 cast(count_big(*) as float)/nullif(m.skill_denominator,0) as skill_share,
 m.source,m.scope_version,m.rule_version,m.dictionary_version,m.body_hash_version,m.skill_text_scope
from {{ ref('cd_eligible_job_skill') }} s
join {{ ref('cd_scope_summary') }} m on m.build_id=s.build_id
group by s.build_id,s.skill_key,s.skill_name,m.skill_denominator,m.source,m.scope_version,m.rule_version,m.dictionary_version,m.body_hash_version,m.skill_text_scope
