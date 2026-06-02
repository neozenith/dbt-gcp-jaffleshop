{# -----------------------------------------------------------------------------
   Elementary requires its `test` materialization to capture each test's results.
   dbt 1.8+ no longer lets an installed package implicitly override a built-in
   materialization (security: GHSA-p3f3-5ccg-83xq), so we re-export it explicitly
   here. `default` covers BigQuery (Snowflake would use materialization_test_snowflake).
   See: https://docs.elementary-data.com/data-tests/dbt/quickstart-package
----------------------------------------------------------------------------- #}
{% materialization test, default %}
  {{ return(elementary.materialization_test_default()) }}
{% endmaterialization %}
