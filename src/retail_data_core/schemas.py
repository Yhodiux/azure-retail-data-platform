from pyspark.sql.types import (
    DecimalType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


def _field(name, data_type, nullable=True):
    return StructField(name, data_type, nullable)


TABLE_SCHEMAS = {
    "customers": StructType([
        _field("customer_id", StringType(), False),
        _field("customer_unique_id", StringType(), False),
        _field("customer_zip_code_prefix", StringType(), True),
        _field("customer_city", StringType(), True),
        _field("customer_state", StringType(), True),
    ]),
    "orders": StructType([
        _field("order_id", StringType(), False),
        _field("customer_id", StringType(), False),
        _field("order_status", StringType(), True),
        _field("order_purchase_timestamp", TimestampType(), True),
        _field("order_approved_at", TimestampType(), True),
        _field("order_delivered_carrier_date", TimestampType(), True),
        _field("order_delivered_customer_date", TimestampType(), True),
        _field("order_estimated_delivery_date", TimestampType(), True),
    ]),
    "order_items": StructType([
        _field("order_id", StringType(), False),
        _field("order_item_id", IntegerType(), False),
        _field("product_id", StringType(), False),
        _field("seller_id", StringType(), False),
        _field("shipping_limit_date", TimestampType(), True),
        _field("price", DecimalType(12, 2), True),
        _field("freight_value", DecimalType(12, 2), True),
    ]),
    "order_payments": StructType([
        _field("order_id", StringType(), False),
        _field("payment_sequential", IntegerType(), False),
        _field("payment_type", StringType(), True),
        _field("payment_installments", IntegerType(), True),
        _field("payment_value", DecimalType(12, 2), True),
    ]),
    "products": StructType([
        _field("product_id", StringType(), False),
        _field("product_category_name", StringType(), True),
        _field("product_name_lenght", IntegerType(), True),
        _field("product_description_lenght", IntegerType(), True),
        _field("product_photos_qty", IntegerType(), True),
        _field("product_weight_g", IntegerType(), True),
        _field("product_length_cm", IntegerType(), True),
        _field("product_height_cm", IntegerType(), True),
        _field("product_width_cm", IntegerType(), True),
    ]),
    "sellers": StructType([
        _field("seller_id", StringType(), False),
        _field("seller_zip_code_prefix", StringType(), True),
        _field("seller_city", StringType(), True),
        _field("seller_state", StringType(), True),
    ]),
}


def get_table_schema(table_name):
    try:
        return TABLE_SCHEMAS[table_name]
    except KeyError as exc:
        supported_tables = ", ".join(sorted(TABLE_SCHEMAS))
        raise ValueError(
            f"Unsupported TABLE_NAME '{table_name}'. Supported values: {supported_tables}"
        ) from exc

