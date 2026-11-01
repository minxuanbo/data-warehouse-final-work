select s.build_id
from {{ source('audit','analysis_selection') }} s
left join {{ source('audit','analysis_build') }} b on b.build_id=s.build_id and b.batch_id=s.batch_id
where b.build_id is null or b.status<>'ready'
