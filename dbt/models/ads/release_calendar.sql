with bounds as (
 select f.release_id,min(d.calendar_date) as first_day,max(d.calendar_date) as last_day
 from {{ source('dwd','fact_job_daily') }} f
 join {{ source('dim','calendar_date') }} d on d.date_key=f.date_key group by f.release_id
)
select b.release_id,d.* from bounds b
join {{ source('dim','calendar_date') }} d on d.calendar_date between b.first_day and b.last_day
where {{ published_release('b.release_id') }}
