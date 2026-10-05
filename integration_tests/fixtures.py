"""Synthetic CSVs published through the REAL existing Bronze COMPLETE producer."""
import csv
import shutil
from pathlib import Path
from types import SimpleNamespace

from tooling.landing_snapshot import EXPECTED_FILES, make_manifest
from tooling.bronze_verification import verify_and_publish, json_bytes
from integration.databricks.contracts import FACTORY, ACCOUNT, sha256

RID = '11111111-1111-4111-8111-111111111111'
CSV_TABLES = {
    'customers': (['customer_id','customer_unique_id','customer_zip_code_prefix','customer_city','customer_state'],
                  ['c1','u1','01001',' city ','SP']),
    'orders': (['order_id','customer_id','order_status','order_purchase_timestamp','order_approved_at',
                'order_delivered_carrier_date','order_delivered_customer_date','order_estimated_delivery_date'],
               ['o1','c1','delivered','2018-01-01 10:00:00','','','','2018-01-05 10:00:00']),
    'order_items': (['order_id','order_item_id','product_id','seller_id','shipping_limit_date','price','freight_value'],
                    ['o1','1','p1','s1','2018-01-02 10:00:00','10.00','1.00']),
    'order_payments': (['order_id','payment_sequential','payment_type','payment_installments','payment_value'],
                       ['o1','1','credit_card','1','11.00']),
    'products': (['product_id','product_category_name','product_name_lenght','product_description_lenght',
                  'product_photos_qty','product_weight_g','product_length_cm','product_height_cm','product_width_cm'],
                 ['p1','category','','','','','','','']),
    'sellers': (['seller_id','seller_zip_code_prefix','seller_city','seller_state'], ['s1','01001','CITY','SP']),
}


class Store:
    def __init__(self, root):
        self.root = root

    def read(self, name, destination):
        p = self.root / name
        if not p.exists():
            return False
        destination.write_bytes(p.read_bytes()); return True

    def create(self, name, source):
        p = self.root / name; p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as stream:
            stream.write(source.read_bytes())

    def list_names(self, prefix):
        return {p.relative_to(self.root).as_posix() for p in self.root.rglob('*')
                if p.is_file() and p.relative_to(self.root).as_posix().startswith(prefix)}


def approved_source(root, customer_state='SP'):
    source = root / 'source'; source.mkdir()
    for name in EXPECTED_FILES:
        (source / name).write_text('synthetic,unused\n',encoding='utf-8')
    for name, (header,row) in CSV_TABLES.items():
        row = list(row)
        if name == 'customers':
            row[-1] = customer_state
        with (source / ('olist_'+name+'_dataset.csv')).open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f); writer.writerow(header); writer.writerow(row)
    m=make_manifest(source); sid=m['snapshot_id']
    stores={area:Store(root/area) for area in ['landing','bronze','audit']}
    for area,relative in [('landing',f'olist/{sid}'),('bronze',f'olist/{sid}/attempts/{RID}')]:
        folder=stores[area].root/relative; (folder/'data').mkdir(parents=True)
        (folder/'manifest.json').write_bytes(json_bytes(m))
        for name in EXPECTED_FILES: shutil.copyfile(source/name,folder/'data'/name)
    run={'runId':RID,'status':'Succeeded','pipelineName':'pl_landing_to_bronze_candidate',
         'parameters':{'snapshot_id':sid},'runStart':'2026-10-02T00:00:00Z','runEnd':'2026-10-02T00:01:00Z'}
    result=verify_and_publish(sid,RID,account=ACCOUNT,factory_id=FACTORY,
                              run_reader=SimpleNamespace(get_run=lambda _:run),**stores)
    roots={area:root/area/'olist' for area in ['audit','bronze','silver']}
    raw=(roots['audit']/sid/'complete.json').read_bytes()
    return sid,sha256(raw),result['complete'],roots
