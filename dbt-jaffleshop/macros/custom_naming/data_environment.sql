{% macro data_environment(node=none, debug_logging=false) -%}

    {#- Default to target.name so target=prod implies DBT_ENV_TYPE=PROD without extra wiring.
        Set DBT_ENV_TYPE explicitly only to decouple env from target (e.g. dry-running prod logic in a dev target). -#}
    {% set data_env = env_var('DBT_ENV_TYPE', target.name) | upper %}

    {%- if data_env not in ['DEV', 'TEST', 'PROD'] -%}
        {{ exceptions.raise_compiler_error("Error: Invalid DBT_ENV_TYPE value: " ~ data_env) }}
    {%- endif -%}

    {% do log("data_environment: DBT_ENV_TYPE: " ~ data_env, info=debug_logging) %}
    {{ data_env }}

{%- endmacro %}
