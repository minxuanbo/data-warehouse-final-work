{% macro published_release(release_column) -%}
exists (select 1 from {{ source('audit','publication_history') }} publication
        where publication.release_id={{ release_column }})
{%- endmacro %}
