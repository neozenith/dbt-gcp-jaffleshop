-- An OUT-OF-PRODUCT consumer of a marts model. It is deliberately UNTAGGED (the dbt_project.yml only
-- tags staging/ + marts/ with `matrix_demo`), so it sits OUTSIDE the named selector. It exists purely
-- so `(selector ∩ state:modified+)+` crosses the product boundary to include it — the one model that
-- distinguishes `--state-modified-plus-plus` from `--state-modified-plus` in the version-matrix
-- corroboration. It is not built by `dbt build --selector matrix_demo` (untagged), only parsed.
select
    order_id,
    order_total
from {{ ref('fct_orders') }}
