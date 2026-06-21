-- MetricFlow time-spine. Required by the semantic layer whenever a semantic model
-- exists. Untagged, so it is NOT part of the matrix_demo product. Parse never runs
-- this SQL; the day-grain series below is duckdb-valid for a real build.
select cast(d as date) as date_day
from range(date '2020-01-01', date '2020-01-05', interval 1 day) as t(d)
