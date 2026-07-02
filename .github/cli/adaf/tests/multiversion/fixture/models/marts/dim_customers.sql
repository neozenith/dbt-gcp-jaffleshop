select
    customer_id,
    cast(count(*) as integer) as order_count,  -- count(*) is BIGINT; the enforced contract declares integer
    max(created_at) as created_at
from {{ ref('stg_orders') }}
group by 1
