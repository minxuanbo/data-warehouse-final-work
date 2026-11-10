select c.*,b.dataset_status,b.coverage_status,b.acceptance_status,b.source_revision
from {{ ref('trial_city_distribution') }} c
join {{ ref('trial_batch_summary') }} b on b.batch_id=c.batch_id
