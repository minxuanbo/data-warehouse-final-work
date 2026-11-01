select j.*,
 cast(case when exists (
   select 1 from {{ source('audit','quality_issue') }} q
   where q.batch_id=j.batch_id
     and json_value(q.payload,'$.source_job_id') COLLATE Latin1_General_100_BIN2=j.source_job_id
     and json_value(q.payload,'$.rule')='education_conflict'
 ) then 1 else 0 end as bit) as education_conflict,
 cast(case when exists (
   select 1 from {{ source('audit','quality_issue') }} q
   where q.batch_id=j.batch_id
     and json_value(q.payload,'$.source_job_id') COLLATE Latin1_General_100_BIN2=j.source_job_id
     and json_value(q.payload,'$.rule')='location_conflict'
 ) then 1 else 0 end as bit) as location_conflict
from {{ ref('trial_job_detail') }} j
