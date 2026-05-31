{% macro generate_database_name(custom_database_name=none, node=none) -%}

    {%- set default_database = target.database -%}
    {%- set data_env = data_environment(node=node) | trim | lower -%}

    {#- Enforce explicit custom database on every model. https://docs.getdbt.com/guides/customize-schema-alias?step=5#always-enforce-custom-schemas -#}
    {%- if custom_database_name is none and node.resource_type == 'model' -%}
        {{ exceptions.raise_compiler_error("Error: No Custom Database Defined for the model " ~ node.name ~ ". This dbt project enforces explicit custom databases for all models.") }}
    {%- endif -%}

    {%- if custom_database_name is none -%}
        {#- Non-model resources (seeds, snapshots, tests) fall through to the env's default GCP project. -#}
        {{ default_database }}
    {%- elif data_env == 'prod' -%}
        {#- Prod: no env suffix. The custom_database_name must map to a real, pre-existing GCP project ID. -#}
        dbt-{{ data_env }}-{{ custom_database_name | trim | lower }}
    {%- else -%}
        {#- Non-prod: append "-<env>" so DEV and TEST land in their own GCP projects. -#}
        {#- BigQuery project IDs allow only [a-z0-9-] — keep lowercase and hyphens. -#}
        dbt-{{ data_env }}-{{ custom_database_name | trim | lower }}
    {%- endif -%}

{%- endmacro %}
