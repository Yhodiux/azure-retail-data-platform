"""Build the separate adapter library; never package adapters into the core."""
import subprocess
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 11):
    raise SystemExit('Use Python 3.11 for the adapter artifact')
root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(root / 'integration'),
                '--no-deps', '--wheel-dir', str(root / 'dist')], check=True)
