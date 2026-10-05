"""Fail closed before upload unless the previously approved wheel is unchanged."""
import hashlib
from pathlib import Path

APPROVED_SHA256 = '955b3b1884c18415d5f8bd06a6fefbead63f36f74f9eade13e7569d0999ada2b'
ADAPTER_SHA256 = 'ff58ac9222ba984953a3d18960a4ff4d0d0081bc3424a67f36e8a0736fe5bf3a'


def main():
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / 'dist').glob('retail_data_core-*.whl'))
    expected = root / 'dist/retail_data_core-0.1.0-py3-none-any.whl'
    if wheels != [expected]:
        raise SystemExit('Exactly the approved wheel must exist')
    observed = hashlib.sha256(expected.read_bytes()).hexdigest()
    if observed != APPROVED_SHA256:
        raise SystemExit('Approved wheel SHA256 mismatch: ' + observed)
    print('Approved wheel verified: ' + observed)
    adapters = list((root / 'dist').glob('retail_databricks_adapters-*.whl'))
    adapter = root / 'dist/retail_databricks_adapters-0.1.0-py3-none-any.whl'
    if adapters != [adapter] or hashlib.sha256(adapter.read_bytes()).hexdigest() != ADAPTER_SHA256:
        raise SystemExit('Reviewed adapter wheel missing or SHA256 mismatch')
    print('Reviewed adapter wheel verified: ' + ADAPTER_SHA256)


if __name__ == '__main__':
    main()
