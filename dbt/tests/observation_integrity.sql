select o.observation_key from {{ source('dwd','fact_posting_observation') }} o
left join {{ source('dim','posting_version') }} v on v.version_key=o.version_key and v.posting_key=o.posting_key
where v.version_key is null or o.observed_at<v.valid_from_observed
   or (v.valid_to_observed is not null and o.observed_at>=v.valid_to_observed)
