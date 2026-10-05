-- Execute on the workspace's -ondemand endpoint, connected to master.
IF DB_ID(N'retail_analytics') IS NULL
    EXEC(N'CREATE DATABASE retail_analytics COLLATE Latin1_General_100_BIN2_UTF8');
GO
