"""Build the plain portable wheel under a supported local Python runtime."""
import subprocess
import sys
from pathlib import Path

if not (3, 8) <= sys.version_info[:2] < (3, 12):
    raise SystemExit("Use Python 3.8-3.11 (recommended 3.11) to build the deployment wheel")
root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, "-m", "pip", "wheel", str(root), "--no-deps",
                "--wheel-dir", str(root / "dist")], check=True)
