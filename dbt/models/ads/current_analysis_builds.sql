select b.*
from {{ ref('cd_scope_summary') }} b
join {{ source('audit','analysis_selection') }} s
 on s.batch_id=b.batch_id and s.build_id=b.build_id
