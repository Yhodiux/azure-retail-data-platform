"""Lazy Databricks APIs; no cloud calls on import or during local validation."""
import argparse
import io

from .contracts import volume_root


def arguments(publish=False):
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot-id', required=True)
    p.add_argument('--complete-sha256', required=True)
    p.add_argument('--catalog', required=True)
    p.add_argument('--schema', required=True)
    if publish:
        p.add_argument('--build-id', required=True)
        p.add_argument('--attempt-id', required=True)
    else:
        p.add_argument('--job-run-id', required=True)
    return p.parse_args()


def services(args):
    from pyspark.sql import SparkSession
    from pyspark.dbutils import DBUtils
    from databricks.sdk import WorkspaceClient
    spark = SparkSession.builder.getOrCreate()
    # Native runtime authentication; no explicit token/PAT or storage credential.
    client = WorkspaceClient()
    silver = volume_root(args.catalog, args.schema, 'silver')

    return spark, DBUtils(spark), files_create(client, silver), {
        area: volume_root(args.catalog, args.schema, area) for area in ['audit','bronze','silver']}


def files_create(client, silver):
    def create(path, data):
        path.relative_to(silver)
        if '..' in path.parts:
            raise ValueError('Unsafe volume path')
        client.files.create_directory(str(path.parent))
        client.files.upload(str(path), io.BytesIO(data), overwrite=False)
    return create


def set_task_values(dbutils, result):
    for key in ['build_id', 'attempt_id']:
        dbutils.jobs.taskValues.set(key=key, value=result[key])
