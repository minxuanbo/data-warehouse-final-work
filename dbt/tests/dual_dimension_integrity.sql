select b.batch_id
from {{ ref('trial_overview') }} b
join (select batch_id,sum(source_posting_count) as count_rows
      from {{ ref('dual_education') }} group by batch_id) e on e.batch_id=b.batch_id
where b.source_posting_count<>e.count_rows
union all
select c.batch_id
from {{ ref('dual_city') }} c join {{ ref('trial_overview') }} b on b.batch_id=c.batch_id
where c.source_posting_count>b.source_posting_count
