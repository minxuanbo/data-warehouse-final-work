select f.release_id,f.date_key,f.job_key,concat(f.release_id,'|',f.date_key,'|',f.job_key) as snapshot_key,
 case v.qualification_kind when 'education' then N'学历' else N'经验' end as qualification_kind,
 q.qualification_rule_version,json_value(v.resolution,'$.value') as qualification_value,
 json_value(v.resolution,'$.status') as resolution_status,e.evidence_field,e.evidence,e.evidence_start,e.evidence_end,
 e.strength,e.degree,j.source,j.source_job_id,j.raw_ref,j.raw_sha256,
 json_value(v.resolution,'$.record_ref') as record_ref,json_query(v.resolution,'$.raw_refs') as raw_refs_json
from {{ source('dwd','fact_job_daily') }} f
join {{ source('dwd','job_qualification_evidence') }} q on q.release_id=f.release_id and q.date_key=f.date_key and q.job_key=f.job_key
join {{ ref('cd_job_detail') }} j on j.build_id=f.build_id and j.observation_key=f.observation_key
cross apply (values ('education',q.education_resolution_json),('experience',q.experience_resolution_json)) v(qualification_kind,resolution)
cross apply openjson(v.resolution,'$.evidence') with (
 evidence_field nvarchar(100) '$.field',evidence nvarchar(max) '$.text',evidence_start int '$.start',evidence_end int '$.end',
 strength nvarchar(40),degree nvarchar(100)) e
where {{ published_release('f.release_id') }}
