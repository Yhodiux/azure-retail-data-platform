-- Execute in retail_analytics using the configured Microsoft Entra admin.
-- The workspace identity has Storage Blob Data Reader only on container Gold.
IF NOT EXISTS (SELECT 1 FROM sys.database_scoped_credentials WHERE name = N'GoldWorkspaceIdentity')
    CREATE DATABASE SCOPED CREDENTIAL GoldWorkspaceIdentity
        WITH IDENTITY = 'Managed Identity';
GO
IF EXISTS (
    SELECT 1 FROM sys.database_scoped_credentials
    WHERE name = N'GoldWorkspaceIdentity' AND credential_identity <> N'Managed Identity'
)
    THROW 50001, 'Existing Gold credential uses a different identity.', 1;
GO
IF NOT EXISTS (SELECT 1 FROM sys.external_data_sources WHERE name = N'GoldParquet')
    CREATE EXTERNAL DATA SOURCE GoldParquet
    WITH (
        LOCATION = 'https://stretaildevc569ffc1.dfs.core.windows.net/gold/olist/olist-sha256-68f181a92070c57c77c00f5b989122a7818787bc0ac3e3b089f19cb01c741d6a/datasets/',
        CREDENTIAL = GoldWorkspaceIdentity
    );
GO
IF EXISTS (
    SELECT 1 FROM sys.external_data_sources
    WHERE name = N'GoldParquet'
      AND (location <> N'https://stretaildevc569ffc1.dfs.core.windows.net/gold/olist/olist-sha256-68f181a92070c57c77c00f5b989122a7818787bc0ac3e3b089f19cb01c741d6a/datasets/'
           OR credential_id <> (SELECT credential_id FROM sys.database_scoped_credentials WHERE name = N'GoldWorkspaceIdentity'))
)
    THROW 50002, 'Existing Gold data source differs from the approved publication.', 1;
GO
