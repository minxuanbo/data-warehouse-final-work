{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
{% macro sqlserver__generate_schema_name(custom_schema_name, node) -%}
  {{ generate_schema_name(custom_schema_name, node) }}
{%- endmacro %}
