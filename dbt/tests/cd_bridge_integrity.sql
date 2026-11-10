select b.build_id from {{ source('dwd','bridge_version_skill') }} b
left join {{ ref('cd_job_detail') }} j on j.build_id=b.build_id and j.version_key=b.version_key
where j.version_key is null
or (b.eligible_for_metric=1 and b.requirement_level=N'不确定')
