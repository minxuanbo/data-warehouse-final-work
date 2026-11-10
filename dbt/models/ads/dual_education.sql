select source,batch_id,
 case when education_conflict=1 then N'冲突待确认'
      else coalesce(education_raw,N'未知') end as education_group,
 count_big(*) as source_posting_count
from {{ ref('dual_job_detail') }}
group by source,batch_id,
 case when education_conflict=1 then N'冲突待确认' else coalesce(education_raw,N'未知') end
