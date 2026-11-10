select j.build_id,j.source,j.source_job_id,j.batch_id,j.version_key,j.is_core,
 s.skill_name,b.requirement_level,b.eligible_for_metric,b.evidence_count,b.evidence_json,
 j.dictionary_version,j.rule_version,j.scope_version,j.body_hash_version,j.skill_text_scope
from {{ ref('cd_job_detail') }} j
join {{ source('dwd','bridge_version_skill') }} b on b.build_id=j.build_id and b.version_key=j.version_key
join {{ source('dim','skill') }} s on s.skill_key=b.skill_key
