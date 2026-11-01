select build_id from {{ ref('cd_job_detail') }}
where (body_hash_version='skills-body-1.1' and skill_text_scope<>'description_raw+requirements_raw+additional_requirements_raw')
   or (body_hash_version='skills-body-1.0' and skill_text_scope<>'description_raw+requirements_raw')
