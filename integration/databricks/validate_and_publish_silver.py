"""Re-read persisted Silver; publish build COMPLETE only after validation."""
from integration.databricks.pipeline import validate_and_publish
from integration.databricks.runtime import arguments, services


def main():
    args = arguments(publish=True)
    spark, _, create, roots = services(args)
    result = validate_and_publish(spark, snapshot=args.snapshot_id, complete_hash=args.complete_sha256,
                                  selected_build=args.build_id, selected_attempt=args.attempt_id,
                                  create=create, **roots)
    print(result)


if __name__ == '__main__':
    main()
