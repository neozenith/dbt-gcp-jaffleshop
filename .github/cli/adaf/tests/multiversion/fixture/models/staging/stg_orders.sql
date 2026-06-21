select
    order_id,
    customer_id,
    order_total,
    created_at
from {{ source('raw', 'orders') }}
