select
    customer_id,
    count(*) as order_count,
    max(created_at) as created_at
from {{ ref('stg_orders') }}
group by 1
