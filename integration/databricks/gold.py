"""One approved Silver publication to five Parquet analytics datasets."""
import re
from decimal import Decimal

from .contracts import attempt_id, digest, json_bytes, read_json, sha256

# Explicit analytical grains and expected column types; business logic is in core.
COMMON = {'total_orders': 'bigint', 'total_sales': 'decimal', 'delivered_orders': 'bigint'}
ITEMS = {'total_items': 'bigint', 'delivered_items': 'bigint',
         'delivered_product_revenue': 'decimal', 'delivered_freight_value': 'decimal'}
PAYMENTS = {'total_payment_records': 'bigint', 'delivered_payment_records': 'bigint',
            'delivered_payment_value': 'decimal'}
SCHEMAS = {
    'sales_by_state': {**COMMON, **ITEMS, 'customer_state': 'string',
                       'total_freight': 'decimal', 'avg_ticket': 'decimal',
                       'delivered_avg_ticket': 'decimal'},
    'sales_by_category': {**COMMON, **ITEMS, 'product_category_name': 'string',
                          'avg_price': 'decimal', 'delivered_avg_item_price': 'decimal',
                          'delivered_avg_ticket': 'decimal'},
    'sales_by_payment_type': {**COMMON, **PAYMENTS, 'payment_type': 'string',
                              'avg_payment_value': 'decimal', 'delivered_avg_payment_value': 'decimal',
                              'delivered_avg_order_payment_value': 'decimal'},
    'top_sellers': {**COMMON, **ITEMS, 'seller_id': 'string', 'seller_state': 'string',
                    'delivered_avg_item_price': 'decimal',
                    'delivered_first_sale_at': 'timestamp', 'delivered_last_sale_at': 'timestamp',
                    'delivered_avg_order_product_revenue': 'decimal'},
    'top_customers': {**COMMON, **PAYMENTS, 'customer_unique_id': 'string', 'customer_state': 'string',
                      'avg_ticket': 'decimal', 'delivered_avg_order_payment_value': 'decimal',
                      'delivered_first_purchase_at': 'timestamp', 'delivered_last_purchase_at': 'timestamp'},
}
KEYS = {'sales_by_state': ['customer_state'], 'sales_by_category': ['product_category_name'],
        'sales_by_payment_type': ['payment_type'], 'top_sellers': ['seller_id', 'seller_state'],
        'top_customers': ['customer_unique_id', 'customer_state']}


def silver_publication(silver, snapshot, build_id, complete_hash):
    if not re.fullmatch(r'olist-sha256-[0-9a-f]{64}', snapshot):
        raise ValueError('Invalid snapshot_id')
    if not re.fullmatch(r'silver-sha256-[0-9a-f]{64}', build_id):
        raise ValueError('Invalid silver_build_id')
    root = silver / snapshot / 'builds' / build_id
    raw = (root / 'complete.json').read_bytes()
    if sha256(raw) != digest(complete_hash):
        raise ValueError('Approved Silver COMPLETE hash mismatch')
    complete = read_json(raw, 'Silver COMPLETE')
    if (complete.get('status') != 'COMPLETE' or complete.get('build_id') != build_id
            or complete.get('spec', {}).get('snapshot_id') != snapshot):
        raise ValueError('Silver publication identity mismatch')
    return root / 'attempts' / attempt_id(complete['attempt_id']) / 'tables', complete


def transform(tables):
    from retail_data_core import gold_transformations as g
    t = tables
    return {
        'sales_by_state': g.build_sales_by_state(t['orders'], t['customers'], t['order_items']),
        'sales_by_category': g.build_sales_by_category(t['orders'], t['order_items'], t['products']),
        'sales_by_payment_type': g.build_sales_by_payment_type(t['orders'], t['order_payments']),
        'top_sellers': g.build_top_sellers(t['orders'], t['order_items'], t['sellers']),
        'top_customers': g.build_top_customers(t['customers'], t['orders'], t['order_payments']),
    }


def validate_dataset(name, df):
    from pyspark.sql import functions as F
    observed = {f.name: ('decimal' if f.dataType.typeName() == 'decimal'
                         else f.dataType.simpleString()) for f in df.schema.fields}
    if observed != SCHEMAS[name]:
        raise ValueError('Gold schema mismatch: ' + name)
    count = df.count()
    if count == 0:
        raise ValueError('Empty Gold dataset: ' + name)
    bad = F.lit(False)
    for key in KEYS[name]:
        bad = bad | F.col(key).isNull() | (F.trim(F.col(key)) == '')
    for column, kind in SCHEMAS[name].items():
        if kind in {'decimal', 'bigint'}:
            bad = bad | (F.col(column) < 0)
            # Delivered averages are legitimately NULL for groups without delivery.
            if not column.startswith('delivered_avg'):
                bad = bad | F.col(column).isNull()
            else:
                bad = bad | ((F.col('delivered_orders') > 0) & F.col(column).isNull())
    bad = bad | (F.col('delivered_orders') > F.col('total_orders')) | (F.col('total_orders') <= 0)
    for total, delivered in [('total_items', 'delivered_items'),
                              ('total_payment_records', 'delivered_payment_records')]:
        if total in df.columns:
            bad = bad | (F.col(delivered) > F.col(total)) | (F.col(total) <= 0)
    if df.filter(bad).limit(1).count():
        raise ValueError('Invalid Gold keys/metrics: ' + name)
    if df.select(*KEYS[name]).distinct().count() != count:
        raise ValueError('Duplicate analytical grain: ' + name)
    return {'row_count': count, 'schema': df.schema.jsonValue(), 'validation': 'PASSED'}


def reconcile(outputs, tables):
    from pyspark.sql import functions as F
    def total(df, column):
        return df.agg(F.sum(column)).first()[0]
    item_sales = total(tables['order_items'], 'price')
    payment_sales = total(tables['order_payments'], 'payment_value')
    checks = {}
    for name, df in outputs.items():
        expected = payment_sales if name in {'sales_by_payment_type', 'top_customers'} else item_sales
        actual = total(df, 'total_sales')
        if abs(actual - expected) > Decimal('0.01'):
            raise ValueError('Gold sales reconciliation failed: ' + name)
        checks[name] = {'expected_sales': str(expected), 'observed_sales': str(actual), 'status': 'PASSED'}
    for name in ['sales_by_state', 'sales_by_category', 'top_sellers']:
        if total(outputs[name], 'total_items') != tables['order_items'].count():
            raise ValueError('Item reconciliation failed: ' + name)
    for name in ['sales_by_payment_type', 'top_customers']:
        if total(outputs[name], 'total_payment_records') != tables['order_payments'].count():
            raise ValueError('Payment record reconciliation failed: ' + name)
    return checks


def build_gold(spark, *, silver, gold, snapshot, build_id, complete_hash, job_run_id, create):
    attempt_id(job_run_id)
    source, complete = silver_publication(silver, snapshot, build_id, complete_hash)
    target = gold / snapshot
    if target.exists():
        raise ValueError('Gold output already exists; no automatic overwrite/retry')
    spark.conf.set('spark.sql.session.timeZone', 'UTC')
    tables = {name: spark.read.parquet(str(source / name)) for name in
              ['customers', 'orders', 'order_items', 'order_payments', 'products', 'sellers']}
    outputs = transform(tables)
    for name, df in outputs.items():
        validate_dataset(name, df)
    reconcile(outputs, tables)
    for name, df in outputs.items():
        df.write.mode('errorifexists').parquet(str(target / 'datasets' / name))
    persisted = {name: spark.read.parquet(str(target / 'datasets' / name)) for name in SCHEMAS}
    evidence = {name: validate_dataset(name, df) for name, df in persisted.items()}
    checks = reconcile(persisted, tables)
    report = {'status': 'PASSED', 'format': 'parquet', 'snapshot_id': snapshot,
              'silver_build_id': build_id, 'silver_attempt_id': complete['attempt_id'],
              'silver_complete_sha256': complete_hash, 'job_run_id': job_run_id,
              'datasets': evidence, 'reconciliations': checks}
    create(target / 'validation.json', json_bytes(report))
    return report
