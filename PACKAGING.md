# Portable core packaging — Block 4C.2

The deployment wheel has no mandatory dependencies. Databricks supplies
PySpark 3.5.0 in DBR 15.4 LTS; install the plain wheel, never the `local-test`
extra there. Python remains `>=3.8,<3.12`, including DBR Python 3.11.11.
The transformation sources are unchanged and contain no cloud SDK imports.

For a Python 3.11 local environment:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install ".[local-test]"
.venv/Scripts/python -m pip wheel . --no-deps --wheel-dir dist
python -B -m unittest discover -s packaging_tests -v
python -B -m unittest discover -s tooling/tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_tests.ps1
```

`local-test` pins PySpark 3.5.4. The existing core test runner additionally fixes
the Spark/Java/Python environment using the digest-pinned Apache Spark 3.5.4
Docker image with no network access. It executes only local Spark, not Databricks.
Build isolation pins setuptools 75.8.0. Keep one release wheel in `dist` for the
artifact contract tests; do not install its optional extra on Databricks.

Block 4C.2 verification: the available host is Python 3.14.6, outside the
package's supported runtime. The pure wheel was built with
`python -m pip wheel . --no-deps --ignore-requires-python --wheel-dir dist`
as an artifact-only check, not a supported execution environment. Wheel tests
inspect actual METADATA, its pure Python tag, exact source bytes and imports.
A pip dry-run targeting Python 3.11 with `--no-index --ignore-installed
--only-binary=:all:` resolves only `retail-data-core`, proving installation
does not request replacement PySpark. No package was installed on Databricks.
DBR integration remains untested until an authorized compute block.
