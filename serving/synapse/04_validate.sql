SELECT v.name AS view_name
FROM sys.views AS v
JOIN sys.schemas AS s ON v.schema_id = s.schema_id
WHERE s.name = 'dbo' AND v.name IN (
    'vw_sales_by_state', 'vw_sales_by_category', 'vw_sales_by_payment_type',
    'vw_top_sellers', 'vw_top_customers'
)
ORDER BY v.name;
GO
SELECT 'sales_by_state' AS dataset, COUNT_BIG(*) AS row_count FROM dbo.vw_sales_by_state
UNION ALL
SELECT 'sales_by_category', COUNT_BIG(*) FROM dbo.vw_sales_by_category
UNION ALL
SELECT 'sales_by_payment_type', COUNT_BIG(*) FROM dbo.vw_sales_by_payment_type
UNION ALL
SELECT 'top_sellers', COUNT_BIG(*) FROM dbo.vw_top_sellers
UNION ALL
SELECT 'top_customers', COUNT_BIG(*) FROM dbo.vw_top_customers;
GO
