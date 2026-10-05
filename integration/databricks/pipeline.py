"""Silver orchestration; Spark is injected and all business logic stays in core."""
import hashlib
import re
from pathlib import Path

from .contracts import (TABLE_FILES, CSV_OPTIONS, attempt_id, build_id, build_root,
                        build_spec, digest, json_bytes, parse_complete, publish_marker,
                        read_json, resolve_source, sha256, validate_run)


def code_digest():
    import retail_data_core
    roots = [Path(retail_data_core.__file__).parent, Path(__file__).parent]
    h = hashlib.sha256()
    for root in roots:
        for path in sorted(root.glob('*.py')):
            h.update(json_bytes({"package": root.name, "file": path.name}))
            h.update(path.read_bytes())
    return h.hexdigest()


def local_create(path, data):
    """Only for filesystem unit tests; Databricks uses Files API overwrite=false."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def context(snapshot, complete_hash, audit, bronze, silver):
    if not isinstance(snapshot, str) or not re.fullmatch('olist-sha256-[0-9a-f]{64}', snapshot):
        raise ValueError('Invalid snapshot_id')
    digest(complete_hash)
    c = parse_complete((audit / snapshot / 'complete.json').read_bytes(), snapshot, complete_hash)
    candidate = resolve_source(c, audit, bronze)
    spec = build_spec(c, complete_hash, code_digest())
    return candidate, spec, build_root(silver, spec)


def complete_attempt(root, spec):
    path = root / 'complete.json'
    if not path.exists():
        return None
    c = read_json(path.read_bytes(), 'Silver COMPLETE')
    keys = {'schema_version', 'status', 'build_id', 'attempt_id', 'spec',
            'manifest_sha256', 'validation_sha256'}
    if (set(c) != keys or type(c.get('schema_version')) is not int or c['schema_version'] != 1
            or c.get('status') != 'COMPLETE' or c.get('spec') != spec or c.get('build_id') != build_id(spec)):
        raise ValueError('Incompatible existing Silver COMPLETE')
    selected = attempt_id(c['attempt_id'])
    for name in ['manifest', 'validation']:
        raw = (root / 'attempts' / selected / (name + '.json')).read_bytes()
        if sha256(raw) != digest(c[name + '_sha256']):
            raise ValueError('COMPLETE evidence hash mismatch')
    return selected


def validate_frames(frames):
    from retail_data_core.data_quality import validate_table_quality, validate_referential_integrity
    if set(frames) != set(TABLE_FILES):
        raise ValueError('Unexpected Silver table set')
    for name, df in sorted(frames.items()):
        validate_table_quality(df, name)
    return validate_referential_integrity(frames)


def persisted_manifest(spark, attempt):
    table_root = attempt / 'tables'
    if {p.name for p in table_root.iterdir()} != set(TABLE_FILES):
        raise ValueError('Unexpected persisted table inventory')
    frames, tables = {}, {}
    for name in sorted(TABLE_FILES):
        folder = table_root / name
        frames[name] = spark.read.parquet(str(folder))
        inventory = []
        for file in sorted(p for p in folder.rglob('*') if p.is_file()):
            h = hashlib.sha256(); size = 0
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk); size += len(chunk)
            inventory.append({'path': file.relative_to(folder).as_posix(),
                              'size_bytes': size, 'sha256': h.hexdigest()})
        if not any(f['path'].endswith('.parquet') for f in inventory):
            raise ValueError('Missing persisted Parquet files')
        tables[name] = {'row_count': frames[name].count(),
                        'schema': frames[name].schema.jsonValue(), 'files': inventory}
    return frames, {'schema_version': 1, 'tables': tables}


def build(spark, *, snapshot, complete_hash, job_run_id, audit, bronze, silver, create):
    attempt_id(job_run_id)
    candidate, spec, root = context(snapshot, complete_hash, audit, bronze, silver)
    selected = complete_attempt(root, spec) or job_run_id
    attempt = root / 'attempts' / selected
    if attempt.exists():
        # Finished attempts are reusable, partial attempts are never overwritten.
        if not (attempt / 'run.json').exists():
            raise ValueError('Partial attempt exists; use a new job run, do not repair/overwrite')
        validate_run(read_json((attempt / 'run.json').read_bytes(), 'run'), spec, selected)
        if not (attempt / 'manifest.json').is_file():
            raise ValueError('Finished attempt missing manifest')
        return {'build_id': build_id(spec), 'attempt_id': selected}
    from retail_data_core.schemas import get_table_schema
    from retail_data_core.silver_transformations import build_silver
    spark.conf.set('spark.sql.session.timeZone', 'UTC')
    frames, input_counts = {}, {}
    # All source checks and core DQ must pass before any Silver write.
    for name, filename in sorted(TABLE_FILES.items()):
        df = spark.read.options(**CSV_OPTIONS).schema(get_table_schema(name)).csv(str(candidate / 'data' / filename))
        input_counts[name] = df.count()
        frames[name] = build_silver(df, name)
        if frames[name].count() != input_counts[name]:
            raise ValueError('Unexpected row-count change: ' + name)
    relationships = validate_frames(frames)
    # Detect source/evidence changes during Spark evaluation before any write.
    candidate_check, spec_check, _ = context(snapshot, complete_hash, audit, bronze, silver)
    if spec_check != spec or candidate_check != candidate:
        raise ValueError('Source changed during build')
    create(attempt / 'intent.json', json_bytes({'spec': spec, 'attempt_id': selected}))
    for name, frame in sorted(frames.items()):
        frame.write.mode('errorifexists').parquet(str(attempt / 'tables' / name))
    persisted, manifest = persisted_manifest(spark, attempt)
    if any(manifest['tables'][name]['row_count'] != input_counts[name] for name in TABLE_FILES):
        raise ValueError('Persisted row-count mismatch')
    validate_frames(persisted)
    publish_marker(attempt / 'manifest.json', manifest, create)
    publish_marker(attempt / 'dq.json', {'schema_version': 1, 'status': 'PASSED',
                                        'relationships': relationships, 'input_counts': input_counts}, create)
    run = {'schema_version': 1, 'status': 'WRITTEN', 'build_id': build_id(spec),
           'attempt_id': selected, 'spec': spec, 'tables': sorted(TABLE_FILES)}
    publish_marker(attempt / 'run.json', run, create)
    return {'build_id': build_id(spec), 'attempt_id': selected}


def validate_and_publish(spark, *, snapshot, complete_hash, selected_build, selected_attempt,
                         audit, bronze, silver, create):
    _, spec, root = context(snapshot, complete_hash, audit, bronze, silver)
    if selected_build != build_id(spec):
        raise ValueError('Task build identity mismatch')
    selected_attempt = attempt_id(selected_attempt)
    previous = complete_attempt(root, spec)
    if previous is not None and previous != selected_attempt:
        raise ValueError('COMPLETE belongs to another attempt; no overwrite')
    attempt = root / 'attempts' / selected_attempt
    run = read_json((attempt / 'run.json').read_bytes(), 'run')
    validate_run(run, spec, selected_attempt)
    if read_json((attempt / 'intent.json').read_bytes(), 'intent') != {'spec': spec, 'attempt_id': selected_attempt}:
        raise ValueError('Attempt intent mismatch')
    if {p.name for p in attempt.iterdir()} - {'tables','intent.json','run.json','manifest.json','dq.json','validation.json'}:
        raise ValueError('Unexpected attempt artifact')
    spark.conf.set('spark.sql.session.timeZone', 'UTC')
    frames, observed = persisted_manifest(spark, attempt)
    raw_manifest = (attempt / 'manifest.json').read_bytes()
    if read_json(raw_manifest, 'manifest') != observed:
        raise ValueError('Persisted manifest mismatch')
    relationships = validate_frames(frames)
    dq = read_json((attempt / 'dq.json').read_bytes(), 'DQ')
    if dq != {'schema_version': 1, 'status': 'PASSED', 'relationships': relationships,
              'input_counts': {name: observed['tables'][name]['row_count'] for name in TABLE_FILES}}:
        raise ValueError('Persisted DQ/count mismatch')
    validation = {'schema_version': 1, 'status': 'PASSED', 'build_id': selected_build,
                  'attempt_id': selected_attempt, 'manifest_sha256': sha256(raw_manifest),
                  'run_sha256': sha256((attempt / 'run.json').read_bytes()),
                  'dq_sha256': sha256((attempt / 'dq.json').read_bytes()),
                  'relationships': relationships, 'tables': sorted(TABLE_FILES)}
    # Recheck bytes after Spark DQ and recheck approved source before publication.
    _, observed_again = persisted_manifest(spark, attempt)
    if observed_again != observed:
        raise ValueError('Persisted data changed during validation')
    _, current_spec, _ = context(snapshot, complete_hash, audit, bronze, silver)
    if current_spec != spec:
        raise ValueError('Approved source changed during validation')
    publish_marker(attempt / 'validation.json', validation, create)
    complete = {'schema_version': 1, 'status': 'COMPLETE', 'build_id': selected_build,
                'attempt_id': selected_attempt, 'spec': spec,
                'manifest_sha256': sha256(raw_manifest), 'validation_sha256': sha256(json_bytes(validation))}
    return publish_marker(root / 'complete.json', complete, create)
