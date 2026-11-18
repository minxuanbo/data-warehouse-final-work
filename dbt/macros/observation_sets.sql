{% macro observation_set_count(fact, release_id, day_key, previous_key, mode) -%}
(select count_big({% if mode == 'missing_two' %}distinct current_job.job_key{% else %}*{% endif %})
 from {{ fact }} current_job
 where current_job.release_id={{ release_id }} and current_job.is_core=1
 {% if mode == 'missing_two' %}
 and current_job.date_key<{{ previous_key }}
 and not exists (select 1 from {{ fact }} seen
   where seen.release_id=current_job.release_id and seen.job_key=current_job.job_key and seen.is_core=1
     and seen.date_key in ({{ day_key }},{{ previous_key }}))
 {% else %}
 and current_job.date_key={{ day_key }}
 and not exists (select 1 from {{ fact }} seen
   where seen.release_id=current_job.release_id and seen.job_key=current_job.job_key and seen.is_core=1
   and seen.date_key {% if mode == 'first' %}<{{ day_key }}{% else %}={{ previous_key }}{% endif %})
 {% endif %})
{%- endmacro %}
