select release_id,date_key from {{ ref('release_observed_change') }}
where (is_comparable=0 and (newly_observed_count is not null or content_changed_count is not null
 or first_discovered_count is not null or still_unobserved_count is not null))
 or (is_comparable=1 and (newly_observed_count is null or first_discovered_count is null
 or still_unobserved_count is null or first_discovered_count>newly_observed_count
 or newly_observed_count+content_changed_count>core_posting_count))
