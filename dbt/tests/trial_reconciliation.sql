select b.batch_id from {{ source('audit','collection_batch') }} b
left join {{ ref('trial_overview') }} s on s.batch_id=b.batch_id
where s.source_posting_count is null or s.source_posting_count<>b.record_count
   or s.body_valid_count>s.source_posting_count
