-- Execute in retail_analytics before 02_gold_source.sql.
-- @MasterKeyPassword is a runtime SqlParameter, never a stored SQL literal.
IF NOT EXISTS (
    SELECT 1 FROM sys.symmetric_keys WHERE name = N'##MS_DatabaseMasterKey##'
)
BEGIN
    DECLARE @ddl nvarchar(max) = N'CREATE MASTER KEY ENCRYPTION BY PASSWORD = '
        + QUOTENAME(@MasterKeyPassword, '''') + N';';
    EXEC sys.sp_executesql @ddl;
END;
GO
