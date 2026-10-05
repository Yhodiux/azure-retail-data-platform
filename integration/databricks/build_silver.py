"""Task entry script. Execution is permitted only in a later authorized run."""
from integration.databricks.pipeline import build
from integration.databricks.runtime import arguments, services, set_task_values


def main():
    args = arguments()
    spark, dbutils, create, roots = services(args)
    result = build(spark, snapshot=args.snapshot_id, complete_hash=args.complete_sha256,
                   job_run_id=args.job_run_id, create=create, **roots)
    set_task_values(dbutils, result)


if __name__ == '__main__':
    main()
