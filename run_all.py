"""
run_all.py — Convenience script to run the full project pipeline
================================================================
Run from the project root:
    python run_all.py

Steps:
  1. Generate / process data
  2. Train all models
  3. Run end-to-end pipeline and print summary
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def run(cmd: list[str], label: str):
    print(f"\n{'='*55}")
    print(f"  {label}")
    print('='*55)
    result = subprocess.run(
        [sys.executable] + cmd,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"\n[ERROR] Step failed with code {result.returncode}")
        sys.exit(result.returncode)
    print(f"[OK] {label} — done")


if __name__ == "__main__":
    run(["src/data.py"],     "Step 1-3: Data generation & feature engineering")
    run(["src/forecast.py"], "Step 4: Forecasting model training")
    run(["src/optimize.py"], "Step 5: Optimizer sanity check")
    run(["src/pipeline.py"], "Step 7: End-to-end pipeline")

    print("\n" + "="*55)
    print("  [SUCCESS] All steps complete!")
    print("  Launch the dashboard:")
    print("    streamlit run dashboard/dashboard.py")
    print("="*55)
