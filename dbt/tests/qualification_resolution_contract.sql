select f.release_id,f.date_key,f.job_key
from {{ source('dwd','fact_job_daily') }} f
join {{ source('audit','model_build') }} b on b.release_id=f.release_id
left join {{ source('dwd','job_qualification_evidence') }} q on q.release_id=f.release_id and q.date_key=f.date_key and q.job_key=f.job_key
join {{ source('dim','education') }} ed on ed.education_key=f.education_key
join {{ source('dim','experience') }} ex on ex.experience_key=f.experience_key
where b.normalization_version in ('conformed-cn-1.1','conformed-cn-1.2') and (
 q.job_key is null or json_value(q.education_resolution_json,'$.value')<>ed.education_name
 or json_value(q.experience_resolution_json,'$.value')<>ex.experience_name
 or (json_value(q.education_resolution_json,'$.status') in ('not_stated','preference_only') and ed.education_name<>N'未注明'))
