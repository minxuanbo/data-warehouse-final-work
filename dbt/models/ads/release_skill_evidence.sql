select f.release_id,f.date_key,f.job_key,concat(f.release_id,'|',f.date_key,'|',f.job_key) as snapshot_key,
 e.skill_name,e.eligible_for_metric,x.*
from {{ source('dwd','fact_job_daily') }} f
join {{ ref('cd_skill_evidence') }} e on e.build_id=f.build_id and e.version_key=f.representative_version_key
cross apply openjson(e.evidence_json) with (
 evidence_field nvarchar(100),evidence nvarchar(max),raw_ref nvarchar(1000),
 evidence_start int,evidence_end int,body_hash_version nvarchar(100)
) x
where {{ published_release('f.release_id') }}
