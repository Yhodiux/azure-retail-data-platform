"""Read-only runtime smoke. No transformations, Files API client or writes."""
import argparse
import json
import re
import sys
from pathlib import Path

from integration.databricks.contracts import digest, parse_complete, resolve_source, sha256, volume_root
from tooling.landing_snapshot import validate_manifest


def inspect_source(snapshot, complete_hash, audit, bronze):
    if not isinstance(snapshot, str) or not re.fullmatch('olist-sha256-[0-9a-f]{64}', snapshot):
        raise ValueError('Invalid snapshot_id')
    digest(complete_hash)
    if not audit.is_dir() or not bronze.is_dir():
        raise ValueError('Audit/Bronze volume is not accessible')
    marker = audit / snapshot / 'complete.json'
    raw = marker.read_bytes()
    complete = parse_complete(raw, snapshot, complete_hash)
    candidate = resolve_source(complete, audit, bronze)
    manifest = validate_manifest(json.loads((candidate / 'manifest.json').read_bytes()))
    reads = []
    for entry in sorted(manifest['files'], key=lambda item: item['file_name']):
        # Demonstrate direct FUSE reads without logging customer data.
        with (candidate / 'data' / entry['file_name']).open('rb') as stream:
            header = stream.readline(4096)
            sample = stream.read(1024)
        if not header:
            raise ValueError('Empty CSV header: ' + entry['file_name'])
        reads.append({'file_name': entry['file_name'], 'size_bytes': entry['size_bytes'],
                      'sha256': entry['sha256'], 'header_bytes': len(header),
                      'sample_bytes': len(sample)})
    return {'audit_volume': str(audit), 'bronze_volume': str(bronze),
            'complete_path': str(marker), 'snapshot_id': snapshot,
            'complete_sha256': sha256(raw), 'adf_run_id': complete['adf_run_id'],
            'bronze_path': complete['bronze_path'], 'bronze_volume_path': str(candidate),
            'csv_count': len(reads), 'csv_reads': reads, 'data_writes': 0}


def main():
    parser = argparse.ArgumentParser()
    for name in ['snapshot-id', 'complete-sha256', 'catalog', 'schema']:
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    from pyspark.sql import SparkSession
    import retail_data_core
    from importlib.metadata import version
    spark = SparkSession.builder.getOrCreate()
    runtime = {'python': sys.version.split()[0], 'spark': spark.version,
               'core_version': version('retail-data-core'),
               'core_module': retail_data_core.__file__,
               'current_user': spark.sql('SELECT current_user() AS identity').first()['identity'],
               'cluster_id': spark.conf.get('spark.databricks.clusterUsageTags.clusterId', 'unknown')}
    print('READ_ONLY_SMOKE_RUNTIME=' + json.dumps(runtime, sort_keys=True), flush=True)
    result = inspect_source(args.snapshot_id, args.complete_sha256,
                            volume_root(args.catalog, args.schema, 'audit'),
                            volume_root(args.catalog, args.schema, 'bronze'))
    result.update(runtime)
    result['status'] = 'PASSED'
    print('READ_ONLY_SMOKE_RESULT=' + json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
