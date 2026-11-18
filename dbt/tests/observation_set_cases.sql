-- Read-only set fixtures, never inserted into real recruitment evidence.
-- A disappears for >=2 days; B returns and must not count as first discovery.
with fact as (
 select * from (values (1,1,'A',1),(1,1,'B',1),(1,2,'B',1),(1,2,'C',1),
  (1,3,'C',1),(1,3,'D',1),(1,4,'B',1),(1,4,'D',1),(1,4,'X',0))
 v(release_id,date_key,job_key,is_core)
), cases as (
 select * from (values (2,1,1,1,1,0),(3,2,1,1,1,1),(4,3,1,1,0,1),
  (4,3,0,cast(null as int),cast(null as int),cast(null as int)))
 v(date_key,previous_key,is_comparable,expected_new,expected_first,expected_missing)
), actual as (
 select d.*,
  case when d.is_comparable=1 then {{ observation_set_count('fact','1','d.date_key','d.previous_key','new') }} end as new_count,
  case when d.is_comparable=1 then {{ observation_set_count('fact','1','d.date_key','d.previous_key','first') }} end as first_count,
  case when d.is_comparable=1 then {{ observation_set_count('fact','1','d.date_key','d.previous_key','missing_two') }} end as missing_count
 from cases d
)
select * from actual where coalesce(new_count,-1)<>coalesce(expected_new,-1)
 or coalesce(first_count,-1)<>coalesce(expected_first,-1) or coalesce(missing_count,-1)<>coalesce(expected_missing,-1)
