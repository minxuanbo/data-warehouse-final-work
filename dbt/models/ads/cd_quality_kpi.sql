-- Grain: one immutable analysis build x one project operational KPI.
-- Goals are project acceptance conditions, never employer recruitment targets.
with traced_jobs as (
 select j.build_id,
  cast(case when nullif(j.source_url,N'') is not null
    and len(j.source_revision)=40
    and exists (select 1 from {{ source('ods','raw_response') }} r
                where r.batch_id=j.batch_id and r.relative_path=j.raw_ref
                  and r.sha256=j.raw_sha256)
    then 1 else 0 end as bigint) as is_traced
 from {{ ref('cd_job_detail') }} j
), traceability as (
 select build_id,count_big(*) as posting_count,sum(is_traced) as traced_count
 from traced_jobs group by build_id
), metrics as (
 select s.build_id,s.batch_id,s.source,s.scope_version,s.body_hash_version,
  s.rule_version,s.dictionary_version,c.coverage_status,c.acceptance_status,
  k.kpi_code,k.kpi_name,k.owner_role,k.numerator,k.denominator
 from {{ ref('cd_overview') }} s
 join {{ source('audit','collection_batch') }} c on c.batch_id=s.batch_id
 join traceability t on t.build_id=s.build_id
 cross apply (values
  ('core_body_coverage',N'核心岗位正文覆盖率',N'数据加工与技能分析',s.skill_denominator,s.core_posting_count),
  ('raw_traceability',N'来源岗位原文可追溯率',N'四来源采集与入库',t.traced_count,t.posting_count),
  ('collection_scope_complete',N'批准采集范围遍历完成率',N'来源采集与验收',
   cast(case when c.coverage_status='complete' then 1 else 0 end as bigint),cast(1 as bigint))
 ) k(kpi_code,kpi_name,owner_role,numerator,denominator)
)
select *,
 cast(numerator as float)/nullif(denominator,0) as kpi_value,
 cast(1.0 as float) as goal_value,
 case when denominator=0 then cast(null as int)
      when numerator=denominator then 1 else -1 end as status_value,
 cast(null as int) as trend_value,
 cast('no_comparable_daily_series' as varchar(64)) as trend_reason,
 cast('project_acceptance_v1' as varchar(64)) as target_version
from metrics
