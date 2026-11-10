select c.batch_id from {{ ref('trial_city') }} c
join {{ ref('trial_overview') }} b on b.batch_id=c.batch_id
where c.source_posting_count>b.source_posting_count
