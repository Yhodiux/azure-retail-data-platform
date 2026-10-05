import unittest
from datetime import datetime
from decimal import Decimal as D

from pyspark.sql import SparkSession, functions as F

from retail_data_core.data_quality import (
    DataQualityError, validate_referential_integrity, validate_table_quality,
)
from retail_data_core.schemas import TABLE_SCHEMAS, get_table_schema
from retail_data_core.silver_transformations import build_silver
from retail_data_core.gold_transformations import (
    build_sales_by_state, build_sales_by_category, build_sales_by_payment_type,
    build_top_customers, build_top_sellers,
)


class PortableCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (SparkSession.builder.master("local[2]").appName("portable-core-tests")
                     .config("spark.ui.enabled", "false")
                     .config("spark.ui.showConsoleProgress", "false")
                     .config("spark.sql.shuffle.partitions", "2")
                     .config("spark.sql.session.timeZone", "UTC")
                     .config("spark.sql.warehouse.dir", "/tmp/retail-warehouse")
                     .getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.date = datetime(2018, 1, 1, 10)
        later = datetime(2018, 1, 2, 10)
        rows = {
            "customers": [("c1", "u1", "01001", "CITY", "SP"),
                          ("c2", "u1", "02002", "CITY", "RJ")],
            "orders": [(oid, cid, status, dt, None, None, None, later)
                       for oid, cid, status, dt in [
                           ("o1", "c1", "delivered", cls.date),
                           ("o2", "c1", "canceled", later),
                           ("o3", "c1", "delivered", later),
                           ("o4", "c2", "delivered", later)]],
            "order_items": [(oid, seq, pid, sid, cls.date, D(price), D(freight))
                            for oid, seq, pid, sid, price, freight in [
                                ("o1", 1, "p1", "s1", "100", "10"),
                                ("o1", 2, "p2", "s2", "50", "5"),
                                ("o2", 1, "p1", "s1", "40", "4"),
                                ("o3", 1, "p2", "s1", "25", "2"),
                                ("o4", 1, "p1", "s1", "10", "1")]],
            "order_payments": [(oid, seq, method, 1, D(value))
                               for oid, seq, method, value in [
                                   ("o1", 1, "credit_card", "120"),
                                   ("o1", 2, "voucher", "45"),
                                   ("o2", 1, "credit_card", "44"),
                                   ("o4", 1, "credit_card", "11")]],
            "products": [("p1", "category_a", None, None, None, None, None, None, None),
                         ("p2", None, None, None, None, None, None, None, None)],
            "sellers": [("s1", "01001", "CITY", "SP"), ("s2", "02002", "CITY", "RJ")],
        }
        cls.tables = {name: cls.spark.createDataFrame(data, get_table_schema(name))
                      for name, data in rows.items()}
        t = cls.tables
        cls.outputs = {
            "state": build_sales_by_state(t["orders"], t["customers"], t["order_items"]),
            "category": build_sales_by_category(t["orders"], t["order_items"], t["products"]),
            "payment": build_sales_by_payment_type(t["orders"], t["order_payments"]),
            "customer": build_top_customers(t["customers"], t["orders"], t["order_payments"]),
            "seller": build_top_sellers(t["orders"], t["order_items"], t["sellers"]),
        }
        cls.results = {name: [r.asDict() for r in df.collect()] for name, df in cls.outputs.items()}

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def row(self, output, key, value):
        return next(r for r in self.results[output] if r[key] == value)

    def test_six_silver_contracts_and_normalization(self):
        self.assertEqual(len(TABLE_SCHEMAS), 6)
        for name, df in self.tables.items():
            self.assertEqual(build_silver(df, name).count(), df.count())
        dirty = self.tables["customers"].filter("customer_id = 'c1'").withColumn(
            "customer_city", F.lit(" city ")).withColumn("customer_id", F.lit(" c1 "))
        row = build_silver(dirty, "customers").first()
        self.assertEqual((row.customer_id, row.customer_city, row.customer_zip_code_prefix),
                         ("c1", "CITY", "01001"))

    def test_missing_column_is_rejected(self):
        with self.assertRaisesRegex(DataQualityError, "missing column:customer_id"):
            build_silver(self.tables["customers"].drop("customer_id"), "customers")

    def test_incompatible_type_is_rejected(self):
        bad = self.tables["order_items"].withColumn("price", F.col("price").cast("double"))
        with self.assertRaisesRegex(DataQualityError, "type:price"):
            build_silver(bad, "order_items")

    def test_required_values_and_domains_are_rejected(self):
        for column, value, message in [("customer_id", " ", "required:customer_id"),
                                       ("customer_state", "XX", "allowed_values:customer_state")]:
            with self.subTest(column=column):
                with self.assertRaisesRegex(DataQualityError, message):
                    build_silver(self.tables["customers"].withColumn(column, F.lit(value)), "customers")

    def test_duplicate_composite_key_is_rejected(self):
        df = self.tables["order_payments"]
        with self.assertRaisesRegex(DataQualityError, "unique:order_id,payment_sequential"):
            build_silver(df.unionByName(df), "order_payments")

    def test_negative_and_empty_inputs_are_rejected(self):
        with self.assertRaisesRegex(DataQualityError, "non_negative:price"):
            build_silver(self.tables["order_items"].withColumn(
                "price", F.lit(D("-1")).cast("decimal(12,2)")), "order_items")
        with self.assertRaisesRegex(DataQualityError, "table is empty"):
            validate_table_quality(self.tables["products"].limit(0), "products")

    def test_referential_gate_accepts_valid_and_rejects_orphans(self):
        self.assertEqual(list(validate_referential_integrity(self.tables).values()), [0] * 5)
        bad = dict(self.tables)
        bad["order_items"] = bad["order_items"].withColumn("product_id", F.lit("missing"))
        with self.assertRaisesRegex(DataQualityError, "Referential integrity failed"):
            validate_referential_integrity(bad)

    def test_state_multi_item_delivered_and_legacy(self):
        r = self.row("state", "customer_state", "SP")
        self.assertEqual((r["total_orders"], r["total_items"], r["total_sales"]), (3, 4, D("215")))
        self.assertEqual((r["delivered_orders"], r["delivered_items"],
                          r["delivered_product_revenue"], r["delivered_freight_value"]),
                         (2, 3, D("175"), D("17")))
        self.assertEqual(r["delivered_avg_ticket"], D("87.50"))

    def test_category_unknown_and_nonadditive_orders(self):
        r = self.row("category", "product_category_name", "UNKNOWN")
        self.assertEqual((r["total_orders"], r["total_items"], r["total_sales"]), (2, 2, D("75")))
        self.assertEqual(r["delivered_avg_item_price"], D("37.50"))
        self.assertEqual(sum(r["total_orders"] for r in self.results["category"]), 5)

    def test_payment_records_differ_from_orders(self):
        r = self.row("payment", "payment_type", "credit_card")
        self.assertEqual((r["total_orders"], r["total_sales"], r["delivered_orders"],
                          r["delivered_payment_value"]), (3, D("175"), 2, D("131")))
        r = self.row("customer", "customer_state", "SP")
        self.assertEqual((r["total_orders"], r["total_payment_records"], r["total_sales"],
                          r["delivered_payment_records"], r["delivered_payment_value"]),
                         (2, 3, D("209"), 2, D("165")))

    def test_delivered_without_payment_and_customer_state_grain(self):
        self.assertEqual(len(self.results["customer"]), 2)
        self.assertEqual({r["customer_unique_id"] for r in self.results["customer"]}, {"u1"})
        self.assertEqual(sum(r["delivered_orders"] for r in self.results["state"]), 3)
        self.assertEqual(sum(r["delivered_orders"] for r in self.results["customer"]), 2)
        sp = self.row("customer", "customer_state", "SP")
        self.assertEqual(sp["delivered_first_purchase_at"], self.date)
        self.assertEqual(sp["delivered_last_purchase_at"], self.date)

    def test_seller_price_based_metrics(self):
        r = self.row("seller", "seller_id", "s1")
        self.assertEqual((r["total_orders"], r["total_items"], r["total_sales"],
                          r["delivered_orders"], r["delivered_product_revenue"]),
                         (4, 4, D("175"), 3, D("135")))
        self.assertEqual(r["delivered_avg_order_product_revenue"], D("45"))

    def test_each_gold_grain_is_unique_and_recomputation_is_deterministic(self):
        keys = {"state": ["customer_state"], "category": ["product_category_name"],
                "payment": ["payment_type"], "customer": ["customer_unique_id", "customer_state"],
                "seller": ["seller_id", "seller_state"]}
        for name, df in self.outputs.items():
            with self.subTest(output=name):
                rows = self.results[name]
                self.assertEqual(len(rows), len({tuple(r[k] for k in keys[name]) for r in rows}))
                self.assertCountEqual(rows, [r.asDict() for r in df.collect()])

    def test_no_delivered_group_has_null_average(self):
        t = self.tables
        canceled = t["orders"].withColumn("order_status", F.lit("canceled"))
        rows = build_sales_by_category(canceled, t["order_items"], t["products"]).collect()
        for row in rows:
            self.assertEqual(row.delivered_orders, 0)
            self.assertEqual(row.delivered_product_revenue, D("0"))
            self.assertIsNone(row.delivered_avg_ticket)
            self.assertIsNone(row.delivered_avg_item_price)


if __name__ == "__main__":
    unittest.main()
