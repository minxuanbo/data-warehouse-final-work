select distinct j.build_id,j.batch_id,j.observation_key,j.version_key,s.skill_key,s.skill_name
from {{ ref('cd_job_detail') }} j
join {{ source('dwd','bridge_version_skill') }} b on b.build_id=j.build_id and b.version_key=j.version_key
join {{ source('dim','skill') }} s on s.skill_key=b.skill_key
where j.is_core=1 and j.body_valid=1 and b.eligible_for_metric=1
