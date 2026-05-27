{% macro clean_slice(debug_logging=false) -%}

  {#- Replace characters not allowed in BigQuery dataset names with "_". -#}
  {%- set re = modules.re -%}

  {#- DBT_CLOUD_* variants (https://docs.getdbt.com/docs/build/environment-variables#special-environment-variables)
      take precedence over the generic DBT_* variants used by non-dbt-Cloud runners (GH Actions, GitLab, etc.). -#}
  {%- set pr_id = re.sub("\W", "_",
      env_var('DBT_CLOUD_PR_ID',
        env_var('DBT_PR_ID', '')
      )
    ) | trim | upper -%}
  {%- set run_id = re.sub("\W", "_",
      env_var('DBT_CLOUD_RUN_ID',
        env_var('DBT_RUN_ID', '')
      )
    ) | trim | upper -%}

  {#- DEV environment: branch name (4-level env_var fallback for dbt Cloud, generic dbt, generic CI, and project var). -#}
  {%- set branch_slice = re.sub("\W", "_",
      env_var('DBT_CLOUD_GIT_BRANCH',
        env_var('DBT_GIT_BRANCH',
          env_var('GIT_BRANCH',
            var('git_branch')
          )
        )
      )
    )
   -%}

  {#- TEST environment: PR id + Run id. -#}
  {%- set ci_slice = "PR" ~ pr_id ~ "_RUN" ~ run_id -%}

  {%- set cleaned_slice = "" -%}

  {% if branch_slice is not none and branch_slice | length > 0 %}
    {%- set cleaned_slice = branch_slice -%}
  {% elif ci_slice is not none and ci_slice | length > 7 %}
    {%- set cleaned_slice = ci_slice -%}
  {% endif %}

  {% do log("Clean slice: " ~ cleaned_slice, info=debug_logging) %}
  {{- cleaned_slice | trim -}}

{% endmacro %}
