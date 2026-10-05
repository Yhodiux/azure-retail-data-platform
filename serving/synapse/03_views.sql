-- Explicit SQL schemas preserve the approved Gold Parquet decimal precision/scale.

CREATE OR ALTER VIEW dbo.vw_sales_by_state
AS
SELECT [customer_state],
       [total_orders],
       [total_items],
       [total_sales],
       [total_freight],
       [delivered_orders],
       [delivered_items],
       [delivered_product_revenue],
       [delivered_freight_value],
       [avg_ticket],
       [delivered_avg_ticket]
FROM OPENROWSET(
    BULK 'sales_by_state/*.parquet',
    DATA_SOURCE = 'GoldParquet',
    FORMAT = 'PARQUET'
) WITH (
    [customer_state] varchar(2) COLLATE Latin1_General_100_BIN2_UTF8,
    [total_orders] bigint,
    [total_items] bigint,
    [total_sales] decimal(22,2),
    [total_freight] decimal(22,2),
    [delivered_orders] bigint,
    [delivered_items] bigint,
    [delivered_product_revenue] decimal(23,2),
    [delivered_freight_value] decimal(23,2),
    [avg_ticket] decimal(23,2),
    [delivered_avg_ticket] decimal(24,2)
) AS gold;
GO

CREATE OR ALTER VIEW dbo.vw_sales_by_category
AS
SELECT [product_category_name],
       [total_orders],
       [total_items],
       [total_sales],
       [avg_price],
       [delivered_orders],
       [delivered_items],
       [delivered_product_revenue],
       [delivered_freight_value],
       [delivered_avg_item_price],
       [delivered_avg_ticket]
FROM OPENROWSET(
    BULK 'sales_by_category/*.parquet',
    DATA_SOURCE = 'GoldParquet',
    FORMAT = 'PARQUET'
) WITH (
    [product_category_name] varchar(128) COLLATE Latin1_General_100_BIN2_UTF8,
    [total_orders] bigint,
    [total_items] bigint,
    [total_sales] decimal(22,2),
    [avg_price] decimal(13,2),
    [delivered_orders] bigint,
    [delivered_items] bigint,
    [delivered_product_revenue] decimal(23,2),
    [delivered_freight_value] decimal(23,2),
    [delivered_avg_item_price] decimal(13,2),
    [delivered_avg_ticket] decimal(24,2)
) AS gold;
GO

CREATE OR ALTER VIEW dbo.vw_sales_by_payment_type
AS
SELECT [payment_type],
       [total_orders],
       [total_sales],
       [avg_payment_value],
       [total_payment_records],
       [delivered_orders],
       [delivered_payment_records],
       [delivered_payment_value],
       [delivered_avg_payment_value],
       [delivered_avg_order_payment_value]
FROM OPENROWSET(
    BULK 'sales_by_payment_type/*.parquet',
    DATA_SOURCE = 'GoldParquet',
    FORMAT = 'PARQUET'
) WITH (
    [payment_type] varchar(32) COLLATE Latin1_General_100_BIN2_UTF8,
    [total_orders] bigint,
    [total_sales] decimal(22,2),
    [avg_payment_value] decimal(13,2),
    [total_payment_records] bigint,
    [delivered_orders] bigint,
    [delivered_payment_records] bigint,
    [delivered_payment_value] decimal(23,2),
    [delivered_avg_payment_value] decimal(13,2),
    [delivered_avg_order_payment_value] decimal(24,2)
) AS gold;
GO

CREATE OR ALTER VIEW dbo.vw_top_sellers
AS
SELECT [seller_id],
       [seller_state],
       [total_orders],
       [total_items],
       [total_sales],
       [delivered_orders],
       [delivered_items],
       [delivered_product_revenue],
       [delivered_freight_value],
       [delivered_avg_item_price],
       [delivered_first_sale_at],
       [delivered_last_sale_at],
       [delivered_avg_order_product_revenue]
FROM OPENROWSET(
    BULK 'top_sellers/*.parquet',
    DATA_SOURCE = 'GoldParquet',
    FORMAT = 'PARQUET'
) WITH (
    [seller_id] varchar(32) COLLATE Latin1_General_100_BIN2_UTF8,
    [seller_state] varchar(2) COLLATE Latin1_General_100_BIN2_UTF8,
    [total_orders] bigint,
    [total_items] bigint,
    [total_sales] decimal(23,2),
    [delivered_orders] bigint,
    [delivered_items] bigint,
    [delivered_product_revenue] decimal(23,2),
    [delivered_freight_value] decimal(23,2),
    [delivered_avg_item_price] decimal(13,2),
    [delivered_first_sale_at] datetime2(6),
    [delivered_last_sale_at] datetime2(6),
    [delivered_avg_order_product_revenue] decimal(24,2)
) AS gold;
GO

CREATE OR ALTER VIEW dbo.vw_top_customers
AS
SELECT [customer_unique_id],
       [customer_state],
       [total_orders],
       [total_sales],
       [total_payment_records],
       [delivered_orders],
       [delivered_payment_records],
       [delivered_payment_value],
       [delivered_first_purchase_at],
       [delivered_last_purchase_at],
       [avg_ticket],
       [delivered_avg_order_payment_value]
FROM OPENROWSET(
    BULK 'top_customers/*.parquet',
    DATA_SOURCE = 'GoldParquet',
    FORMAT = 'PARQUET'
) WITH (
    [customer_unique_id] varchar(32) COLLATE Latin1_General_100_BIN2_UTF8,
    [customer_state] varchar(2) COLLATE Latin1_General_100_BIN2_UTF8,
    [total_orders] bigint,
    [total_sales] decimal(23,2),
    [total_payment_records] bigint,
    [delivered_orders] bigint,
    [delivered_payment_records] bigint,
    [delivered_payment_value] decimal(23,2),
    [delivered_first_purchase_at] datetime2(6),
    [delivered_last_purchase_at] datetime2(6),
    [avg_ticket] decimal(24,2),
    [delivered_avg_order_payment_value] decimal(24,2)
) AS gold;
GO
