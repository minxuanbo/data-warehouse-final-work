-- B03: one mutually exclusive category x education x experience x employment group.
select release_id,date_key,source_key,category_key,education_key,experience_key,employment_type_key,
 count_big(*) as core_posting_count,
 sum(case when body_valid=1 then cast(1 as bigint) else 0 end) as skill_denominator
from {{ source('dwd','fact_job_daily') }}
where is_core=1
group by release_id,date_key,source_key,category_key,education_key,experience_key,employment_type_key
