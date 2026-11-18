{{ config(alias='release_skill_profile') }}
select m.release_id,m.date_key,d.calendar_date as analysis_date,s.source_code as source,
 c.category_name as category_group,k.skill_name,m.posting_count,m.skill_denominator,
 cast(m.posting_count as float)/nullif(m.skill_denominator,0) as skill_share
from {{ ref('release_skill_profile') }} m
join {{ source('dim','calendar_date') }} d on d.date_key=m.date_key
join {{ source('dim','source') }} s on s.source_key=m.source_key
join {{ source('dim','job_category') }} c on c.category_key=m.category_key
join {{ source('dim','skill') }} k on k.skill_key=m.skill_key
where {{ published_release('m.release_id') }}
