from pyspark.sql.functions import (
    avg,
    coalesce,
    col,
    count,
    countDistinct,
    lit,
    max as spark_max,
    min as spark_min,
    round,
    sum as spark_sum,
    when,
)


def build_sales_by_state(orders_df, customers_df, order_items_df):
    return (
        orders_df.alias("o")
        .join(
            customers_df.alias("c"),
            col("o.customer_id") == col("c.customer_id"),
            "inner",
        )
        .join(
            order_items_df.alias("oi"),
            col("o.order_id") == col("oi.order_id"),
            "inner",
        )
        .groupBy(col("c.customer_state").alias("customer_state"))
        .agg(
            countDistinct(col("o.order_id")).alias("total_orders"),
            count(col("oi.product_id")).alias("total_items"),
            spark_sum(col("oi.price")).alias("total_sales"),
            spark_sum(col("oi.freight_value")).alias("total_freight"),
            countDistinct(
                when(col("o.order_status") == "delivered", col("o.order_id"))
            ).alias("delivered_orders"),
            spark_sum(
                when(col("o.order_status") == "delivered", 1).otherwise(0)
            ).alias("delivered_items"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.price"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_product_revenue"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.freight_value"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_freight_value"),
        )
        .withColumn(
            "avg_ticket",
            round(col("total_sales") / col("total_orders"), 2),
        )
        .withColumn(
            "delivered_avg_ticket",
            when(
                col("delivered_orders") > 0,
                round(
                    col("delivered_product_revenue") / col("delivered_orders"),
                    2,
                ),
            ),
        )
        .orderBy(col("total_sales").desc())
    )


def build_sales_by_category(orders_df, order_items_df, products_df):
    return (
        orders_df.alias("o")
        .join(
            order_items_df.alias("oi"),
            col("o.order_id") == col("oi.order_id"),
            "inner",
        )
        .join(
            products_df.alias("p"),
            col("oi.product_id") == col("p.product_id"),
            "left",
        )
        .groupBy(
            coalesce(
                col("p.product_category_name"),
                lit("UNKNOWN"),
            ).alias("product_category_name")
        )
        .agg(
            countDistinct(col("o.order_id")).alias("total_orders"),
            count(col("oi.product_id")).alias("total_items"),
            spark_sum(col("oi.price")).alias("total_sales"),
            round(avg(col("oi.price")), 2).alias("avg_price"),
            countDistinct(
                when(col("o.order_status") == "delivered", col("o.order_id"))
            ).alias("delivered_orders"),
            spark_sum(
                when(col("o.order_status") == "delivered", 1).otherwise(0)
            ).alias("delivered_items"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.price"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_product_revenue"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.freight_value"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_freight_value"),
            round(
                avg(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.price"),
                    )
                ),
                2,
            ).alias("delivered_avg_item_price"),
        )
        .withColumn(
            "delivered_avg_ticket",
            when(
                col("delivered_orders") > 0,
                round(
                    col("delivered_product_revenue") / col("delivered_orders"),
                    2,
                ),
            ),
        )
        .orderBy(col("total_sales").desc())
    )


def build_sales_by_payment_type(orders_df, payments_df):
    return (
        orders_df.alias("o")
        .join(
            payments_df.alias("p"),
            col("o.order_id") == col("p.order_id"),
            "inner",
        )
        .groupBy(col("p.payment_type").alias("payment_type"))
        .agg(
            countDistinct(col("o.order_id")).alias("total_orders"),
            spark_sum(col("p.payment_value")).alias("total_sales"),
            round(avg(col("p.payment_value")), 2).alias("avg_payment_value"),
            count(col("p.payment_sequential")).alias("total_payment_records"),
            countDistinct(
                when(col("o.order_status") == "delivered", col("o.order_id"))
            ).alias("delivered_orders"),
            spark_sum(
                when(col("o.order_status") == "delivered", 1).otherwise(0)
            ).alias("delivered_payment_records"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("p.payment_value"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_payment_value"),
            round(
                avg(
                    when(
                        col("o.order_status") == "delivered",
                        col("p.payment_value"),
                    )
                ),
                2,
            ).alias("delivered_avg_payment_value"),
        )
        .withColumn(
            "delivered_avg_order_payment_value",
            when(
                col("delivered_orders") > 0,
                round(
                    col("delivered_payment_value") / col("delivered_orders"),
                    2,
                ),
            ),
        )
        .orderBy(col("total_sales").desc())
    )


def build_top_customers(customers_df, orders_df, payments_df):
    return (
        customers_df.alias("c")
        .join(
            orders_df.alias("o"),
            col("c.customer_id") == col("o.customer_id"),
            "inner",
        )
        .join(
            payments_df.alias("p"),
            col("o.order_id") == col("p.order_id"),
            "inner",
        )
        .groupBy(
            col("c.customer_unique_id").alias("customer_unique_id"),
            col("c.customer_state").alias("customer_state"),
        )
        .agg(
            countDistinct(col("o.order_id")).alias("total_orders"),
            spark_sum(col("p.payment_value")).alias("total_sales"),
            count(col("p.payment_sequential")).alias("total_payment_records"),
            countDistinct(
                when(col("o.order_status") == "delivered", col("o.order_id"))
            ).alias("delivered_orders"),
            spark_sum(
                when(col("o.order_status") == "delivered", 1).otherwise(0)
            ).alias("delivered_payment_records"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("p.payment_value"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_payment_value"),
            spark_min(
                when(
                    col("o.order_status") == "delivered",
                    col("o.order_purchase_timestamp"),
                )
            ).alias("delivered_first_purchase_at"),
            spark_max(
                when(
                    col("o.order_status") == "delivered",
                    col("o.order_purchase_timestamp"),
                )
            ).alias("delivered_last_purchase_at"),
        )
        .withColumn("total_sales", round(col("total_sales"), 2))
        .withColumn(
            "avg_ticket",
            round(col("total_sales") / col("total_orders"), 2),
        )
        .withColumn(
            "delivered_avg_order_payment_value",
            when(
                col("delivered_orders") > 0,
                round(
                    col("delivered_payment_value") / col("delivered_orders"),
                    2,
                ),
            ),
        )
        .orderBy(col("total_sales").desc())
    )


def build_top_sellers(orders_df, order_items_df, sellers_df):
    return (
        orders_df.alias("o")
        .join(
            order_items_df.alias("oi"),
            col("o.order_id") == col("oi.order_id"),
            "inner",
        )
        .join(
            sellers_df.alias("s"),
            col("oi.seller_id") == col("s.seller_id"),
            "left",
        )
        .groupBy(
            col("oi.seller_id").alias("seller_id"),
            col("s.seller_state").alias("seller_state"),
        )
        .agg(
            countDistinct(col("o.order_id")).alias("total_orders"),
            count(col("oi.product_id")).alias("total_items"),
            spark_sum(col("oi.price")).alias("total_sales"),
            countDistinct(
                when(col("o.order_status") == "delivered", col("o.order_id"))
            ).alias("delivered_orders"),
            spark_sum(
                when(col("o.order_status") == "delivered", 1).otherwise(0)
            ).alias("delivered_items"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.price"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_product_revenue"),
            round(
                spark_sum(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.freight_value"),
                    ).otherwise(0)
                ),
                2,
            ).alias("delivered_freight_value"),
            round(
                avg(
                    when(
                        col("o.order_status") == "delivered",
                        col("oi.price"),
                    )
                ),
                2,
            ).alias("delivered_avg_item_price"),
            spark_min(
                when(
                    col("o.order_status") == "delivered",
                    col("o.order_purchase_timestamp"),
                )
            ).alias("delivered_first_sale_at"),
            spark_max(
                when(
                    col("o.order_status") == "delivered",
                    col("o.order_purchase_timestamp"),
                )
            ).alias("delivered_last_sale_at"),
        )
        .withColumn("total_sales", round(col("total_sales"), 2))
        .withColumn(
            "delivered_avg_order_product_revenue",
            when(
                col("delivered_orders") > 0,
                round(
                    col("delivered_product_revenue") / col("delivered_orders"),
                    2,
                ),
            ),
        )
        .orderBy(col("total_sales").desc())
    )
