-- Contract fixtures only: no synthetic records are written into business tables.
-- A third-field-only body belongs in the denominator only for a three-field build.
with cases as (
 select * from (values
  (0,cast(N'熟悉 SQL' as nvarchar(100)),cast('description_raw+requirements_raw+additional_requirements_raw' as varchar(100)),1),
  (0,N'熟悉 SQL','description_raw+requirements_raw',0),
  (0,cast(null as nvarchar(100)),'description_raw+requirements_raw+additional_requirements_raw',0),
  (0,N' '+nchar(9)+nchar(10),'description_raw+requirements_raw+additional_requirements_raw',0),
  (1,cast(null as nvarchar(100)),'description_raw+requirements_raw',1)
 ) v(base_valid,additional_body,text_scope,expected)
)
select * from cases
where {{ skill_body_valid('base_valid','additional_body','text_scope') }}<>expected
