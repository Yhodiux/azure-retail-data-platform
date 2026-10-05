BRAZIL_STATE_CODES = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

ORDER_STATUSES = {
    "approved",
    "canceled",
    "created",
    "delivered",
    "invoiced",
    "processing",
    "shipped",
    "unavailable",
}

PAYMENT_TYPES = {
    "boleto",
    "credit_card",
    "debit_card",
    "not_defined",
    "voucher",
}


TABLE_QUALITY_RULES = {
    "customers": {
        "required": [
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ],
        "unique": [["customer_id"]],
        "allowed_values": {"customer_state": BRAZIL_STATE_CODES},
    },
    "orders": {
        "required": [
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_estimated_delivery_date",
        ],
        "unique": [["order_id"]],
        "allowed_values": {"order_status": ORDER_STATUSES},
    },
    "order_items": {
        "required": [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ],
        "unique": [["order_id", "order_item_id"]],
        "non_negative": ["order_item_id", "price", "freight_value"],
    },
    "order_payments": {
        "required": [
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ],
        "unique": [["order_id", "payment_sequential"]],
        "non_negative": [
            "payment_sequential",
            "payment_installments",
            "payment_value",
        ],
        "allowed_values": {"payment_type": PAYMENT_TYPES},
    },
    "products": {
        "required": ["product_id"],
        "unique": [["product_id"]],
        "non_negative": [
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ],
    },
    "sellers": {
        "required": [
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state",
        ],
        "unique": [["seller_id"]],
        "allowed_values": {"seller_state": BRAZIL_STATE_CODES},
    },
}


SILVER_RELATIONSHIPS = [
    {
        "name": "orders_customer_id_to_customers",
        "child_table": "orders",
        "child_column": "customer_id",
        "parent_table": "customers",
        "parent_column": "customer_id",
    },
    {
        "name": "order_items_order_id_to_orders",
        "child_table": "order_items",
        "child_column": "order_id",
        "parent_table": "orders",
        "parent_column": "order_id",
    },
    {
        "name": "order_items_product_id_to_products",
        "child_table": "order_items",
        "child_column": "product_id",
        "parent_table": "products",
        "parent_column": "product_id",
    },
    {
        "name": "order_items_seller_id_to_sellers",
        "child_table": "order_items",
        "child_column": "seller_id",
        "parent_table": "sellers",
        "parent_column": "seller_id",
    },
    {
        "name": "payments_order_id_to_orders",
        "child_table": "order_payments",
        "child_column": "order_id",
        "parent_table": "orders",
        "parent_column": "order_id",
    },
]


def get_table_quality_rules(table_name):
    try:
        return TABLE_QUALITY_RULES[table_name]
    except KeyError as exc:
        supported_tables = ", ".join(sorted(TABLE_QUALITY_RULES))
        raise ValueError(
            f"No quality rules registered for '{table_name}'. "
            f"Supported values: {supported_tables}"
        ) from exc

