select build_id,batch_id,scope_version,rule_version,dictionary_version,
 count_big(*) as source_posting_count,
 sum(cast(is_core as bigint)) as core_posting_count,
 sum(case when is_core=1 and body_valid=1 then cast(1 as bigint) else 0 end) as skill_denominator,
 sum(case when additional_requirements_raw is not null then cast(1 as bigint) else 0 end) as additional_requirements_count,
 sum(cast(location_conflict as bigint)) as location_conflict_count,
 sum(cast(experience_conflict as bigint)) as experience_conflict_count
from {{ ref('cd_job_detail') }}
group by build_id,batch_id,scope_version,rule_version,dictionary_version
