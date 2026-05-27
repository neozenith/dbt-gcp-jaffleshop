{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set default_schema = target.schema -%}
    {%- set data_env = data_environment() | trim | upper -%}
    {%- set cleaned_slice = clean_slice() | trim | upper -%}

    {#- Enforce a slice in non-PROD; without it, parallel branches/PRs would collide on dataset names. -#}
    {%- if cleaned_slice is not none and cleaned_slice | length > 0 -%}
        {%- set cleaned_slice = cleaned_slice ~ "__" -%}
    {%- else -%}
        {%- if data_env != 'PROD' -%}
            {{ exceptions.raise_compiler_error(
                "Error: Data Environment is non-PROD and no slice is defined for " ~ node.name ~
                ". Please set environment variable DBT_CLOUD_GIT_BRANCH, or DBT_GIT_BRANCH, or GIT_BRANCH, "
                "or project variable git_branch using --vars \"git_branch: $(git rev-parse --abbrev-ref HEAD)\"."
            ) }}
        {%- endif -%}
    {%- endif -%}

    {#- Enforce explicit custom schema on every model. https://docs.getdbt.com/guides/customize-schema-alias?step=5#always-enforce-custom-schemas -#}
    {%- if custom_schema_name is none and node.resource_type == 'model' -%}
        {{ exceptions.raise_compiler_error("Error: No Custom Schema Defined for the model " ~ node.name ~ ". This dbt project enforces explicit custom schemas for all models.") }}
    {%- endif -%}

    {%- if data_env == 'PROD' -%}
        {%- if custom_schema_name is not none -%}
            {{ custom_schema_name | trim | upper }}
        {%- else -%}
            {#- Should be unreachable for models (guarded above); kept as sane default for non-model resources. -#}
            {{ default_schema | trim | upper }}
        {%- endif -%}
    {%- else -%}
        {{ cleaned_slice | upper }}{{ custom_schema_name | trim | upper }}
    {%- endif -%}

{%- endmacro %}
