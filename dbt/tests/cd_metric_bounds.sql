select build_id from {{ ref('cd_skill_demand') }}
where posting_count>skill_denominator or skill_share<0 or skill_share>1
union all
select build_id from {{ ref('cd_skill_pair') }}
where posting_count>skill_denominator or pair_share<0 or pair_share>1
