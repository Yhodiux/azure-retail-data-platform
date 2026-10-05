-- Product sales and payment value are distinct Gold measures; preserve both.
SELECT TOP (5) customer_state, total_orders, total_sales, delivered_product_revenue
FROM dbo.vw_sales_by_state ORDER BY total_sales DESC, customer_state;
GO
SELECT TOP (5) product_category_name, total_items, total_sales
FROM dbo.vw_sales_by_category ORDER BY total_sales DESC, product_category_name;
GO
SELECT payment_type, total_payment_records, total_sales,
       CAST(100.0 * total_sales / NULLIF(SUM(total_sales) OVER (), 0) AS decimal(7,2)) AS payment_share_pct
FROM dbo.vw_sales_by_payment_type ORDER BY total_sales DESC, payment_type;
GO
SELECT TOP (5) seller_id, seller_state, total_sales, delivered_orders
FROM dbo.vw_top_sellers ORDER BY total_sales DESC, seller_id, seller_state;
GO
SELECT TOP (5) customer_unique_id, customer_state, total_sales, total_orders
FROM dbo.vw_top_customers ORDER BY total_sales DESC, customer_unique_id, customer_state;
GO
