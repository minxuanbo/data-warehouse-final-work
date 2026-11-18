{{ config(alias='release_job_structure') }}
select m.release_id,m.date_key,d.calendar_date as analysis_date,s.source_code as source,
 c.category_name as category_group,m.core_posting_count,m.skill_denominator,m.skilled_posting_count,
 cast(m.skill_denominator as float)/nullif(m.core_posting_count,0) as body_coverage,
 cast(m.skilled_posting_count as float)/nullif(m.skill_denominator,0) as skill_coverage
from {{ ref('release_job_structure') }} m
join {{ source('dim','calendar_date') }} d on d.date_key=m.date_key
join {{ source('dim','source') }} s on s.source_key=m.source_key
join {{ source('dim','job_category') }} c on c.category_key=m.category_key
where {{ published_release('m.release_id') }}
