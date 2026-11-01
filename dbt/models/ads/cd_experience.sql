select build_id,case when experience_conflict=1 then N'冲突待确认'
 else coalesce(experience_raw,N'未知') end as experience_group,
 count_big(*) as posting_count
from {{ ref('cd_job_detail') }}
where is_core=1
group by build_id,case when experience_conflict=1 then N'冲突待确认' else coalesce(experience_raw,N'未知') end
