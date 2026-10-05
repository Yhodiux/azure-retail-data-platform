"""Databricks task launcher for the Gold analytics layer."""
import argparse
import json
import re
from pathlib import Path

from integration.databricks.gold import build_gold
from integration.databricks.runtime import files_create


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot-id', required=True)
    p.add_argument('--silver-build-id', required=True)
    p.add_argument('--complete-sha256', required=True)
    p.add_argument('--job-run-id', required=True)
    p.add_argument('--catalog', required=True)
    p.add_argument('--schema', required=True)
    args = p.parse_args()
    if any(not re.fullmatch('[a-z][a-z0-9_]*', x) for x in [args.catalog, args.schema]):
        raise ValueError('Invalid catalog/schema')
    from databricks.sdk import WorkspaceClient
    from pyspark.sql import SparkSession
    root = Path('/Volumes') / args.catalog / args.schema
    report = build_gold(SparkSession.builder.getOrCreate(), silver=root / 'silver', gold=root / 'gold',
                        snapshot=args.snapshot_id, build_id=args.silver_build_id,
                        complete_hash=args.complete_sha256, job_run_id=args.job_run_id,
                        create=files_create(WorkspaceClient(), root / 'gold'))
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
