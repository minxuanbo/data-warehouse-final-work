{% macro skill_body_valid(base_body_valid, additional_body, text_scope) -%}
cast(case
 when {{ base_body_valid }}=1 then 1
 when charindex('additional_requirements_raw', {{ text_scope }})>0
  and nullif(ltrim(rtrim(replace(replace(replace({{ additional_body }},char(9),' '),char(10),' '),char(13),' '))),N'') is not null then 1
 else 0 end as bit)
{%- endmacro %}
