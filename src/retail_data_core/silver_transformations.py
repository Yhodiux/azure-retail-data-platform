from pyspark.sql.functions import col, trim, upper

from .data_quality import validate_schema, validate_table_quality


def build_silver(df, table_name):
    """Apply the reference sequence: contract, trim, quality, normalization."""
    validate_schema(df, table_name)
    normalized = normalize_string_columns(df)
    validate_table_quality(normalized, table_name)
    return apply_silver_transformations(normalized, table_name)


def normalize_string_columns(df):
    data_types = dict(df.dtypes)
    for column_name in df.columns:
        if data_types[column_name] == "string":
            df = df.withColumn(column_name, trim(col(column_name)))
    return df


def apply_silver_transformations(df, table_name):
    if table_name == "customers":
        return (
            df
            .withColumn("customer_city", upper(col("customer_city")))
            .withColumn("customer_state", upper(col("customer_state")))
            .dropDuplicates(["customer_id"])
        )

    if table_name == "orders":
        return df.dropDuplicates(["order_id"])

    return df

