select a.version_key from {{ source('dim','posting_version') }} a
join {{ source('dim','posting_version') }} b
on a.posting_key=b.posting_key and a.version_key<b.version_key
and a.valid_from_observed<coalesce(b.valid_to_observed,convert(datetimeoffset,'9999-12-31'))
and b.valid_from_observed<coalesce(a.valid_to_observed,convert(datetimeoffset,'9999-12-31'))
