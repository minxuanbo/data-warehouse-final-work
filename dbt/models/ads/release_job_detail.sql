-- One release x date x conservative job identity; retain source identity and evidence.
select f.release_id,f.date_key,dt.calendar_date as analysis_date,dt.calendar_year,dt.calendar_quarter,dt.calendar_month,
 f.job_key,f.build_id,j.observation_key,j.version_key,j.source,j.source_job_id,j.batch_id,j.title_raw,j.source_url,
 co.company_name,cat.category_name as category_group,ed.education_name as education_group,
 ex.experience_name as experience_group,em.employment_type_name as employment_type_group,
 q.qualification_rule_version,
 json_value(q.education_resolution_json,'$.status') as education_resolution_status,
 json_value(q.education_resolution_json,'$.basis') as education_basis,
 case json_value(q.education_resolution_json,'$.status')
  when 'structured' then N'来源学历字段' when 'body_required' then N'正文明确要求'
  when 'preference_only' then N'仅有学历偏好' when 'not_stated' then N'未注明学历'
  when 'conflict' then N'来源与正文冲突' when 'ambiguous' then N'条件复杂待确认'
  when 'unparsed' then N'待解析' else N'历史版本' end as education_basis_label,
 q.education_resolution_json,q.experience_resolution_json,
 j.category_raw,j.education_raw,j.experience_raw,f.is_core,f.body_valid,
 j.location_conflict,j.education_conflict,j.experience_conflict,j.experience_hint,
 j.raw_ref,j.raw_sha256,j.content_json,j.additional_requirements_raw,j.issues_json,j.scope_reason,
 j.body_hash_version,j.dictionary_version,j.rule_version,j.scope_version,j.skill_text_scope,
 b.channel,b.normalization_version,b.mapping_version,
 c.coverage_status,c.acceptance_status,
 case when b.channel='sample' then N'来源岗位样本；覆盖不完整；不推导市场趋势' else N'批准范围内完整观察；不等于企业新增或关闭' end as dataset_note
from {{ source('dwd','fact_job_daily') }} f
join {{ ref('cd_job_detail') }} j on j.build_id=f.build_id and j.observation_key=f.observation_key
join {{ source('audit','model_build') }} b on b.release_id=f.release_id and b.status='ready'
join {{ source('audit','collection_batch') }} c on c.batch_id=j.batch_id
join {{ source('dim','calendar_date') }} dt on dt.date_key=f.date_key
join {{ source('dim','company') }} co on co.company_key=f.company_key
join {{ source('dim','job_category') }} cat on cat.category_key=f.category_key
join {{ source('dim','education') }} ed on ed.education_key=f.education_key
join {{ source('dim','experience') }} ex on ex.experience_key=f.experience_key
join {{ source('dim','employment_type') }} em on em.employment_type_key=f.employment_type_key
left join {{ source('dwd','job_qualification_evidence') }} q
 on q.release_id=f.release_id and q.date_key=f.date_key and q.job_key=f.job_key
where {{ published_release('f.release_id') }}
