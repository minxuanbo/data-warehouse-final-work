{{ config(alias='release_entry_profile') }}
select m.release_id,m.date_key,d.calendar_date as analysis_date,s.source_code as source,
 c.category_name as category_group,e.education_name as education_group,
 x.experience_name as experience_group,t.employment_type_name as employment_type_group,
 m.core_posting_count,m.skill_denominator
from {{ ref('release_entry_profile') }} m
join {{ source('dim','calendar_date') }} d on d.date_key=m.date_key
join {{ source('dim','source') }} s on s.source_key=m.source_key
join {{ source('dim','job_category') }} c on c.category_key=m.category_key
join {{ source('dim','education') }} e on e.education_key=m.education_key
join {{ source('dim','experience') }} x on x.experience_key=m.experience_key
join {{ source('dim','employment_type') }} t on t.employment_type_key=m.employment_type_key
where {{ published_release('m.release_id') }}
