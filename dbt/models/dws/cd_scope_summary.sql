select build_id,batch_id,source,scope_version,rule_version,dictionary_version,body_hash_version,skill_text_scope,
 count_big(*) as source_posting_count,
 sum(cast(is_core as bigint)) as core_posting_count,
 sum(case when is_core=1 and body_valid=1 then cast(1 as bigint) else 0 end) as skill_denominator,
 sum(case when additional_requirements_raw is not null then cast(1 as bigint) else 0 end) as additional_requirements_count,
 sum(cast(location_conflict as bigint)) as location_conflict_count,
 sum(cast(experience_conflict as bigint)) as experience_conflict_count,
 sum(cast(education_conflict as bigint)) as education_conflict_count,
 sum(cast(experience_hint as bigint)) as experience_hint_count
from {{ ref('cd_job_detail') }}
group by build_id,batch_id,source,scope_version,rule_version,dictionary_version,body_hash_version,skill_text_scope
