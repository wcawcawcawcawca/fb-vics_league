"""
ci_pipeline.py
===============
CI entry point for GitHub Actions. Thin wrapper around run_pipeline.run()
that turns a failed Step 4 IP reconciliation into a non-zero exit code, so
the workflow shows a red X instead of silently committing bad numbers.

This intentionally does NOT modify run_pipeline.py -- it just calls the
existing `run()` function and inspects its return value.
"""
import sys

from run_pipeline import run

DATA_PATH = 'data/pennants_over_easy_unified.json'


def main():
    result = run(DATA_PATH)
    gap_table, max_gap, passed = result['heatmap_reconciliation']

    if result['roster_flags']:
        print("\n=== ROSTER RECONSTRUCTION FLAGS (informational) ===")
        for f in result['roster_flags']:
            print("-", f)

    if not passed:
        print(f"\nSTEP 4 RECONCILIATION FAILED: max gap {max_gap:.1f} IP "
              f"exceeds threshold. Failing the build -- see gap table above.")
        sys.exit(1)

    print(f"\nStep 4 reconciliation passed: max gap {max_gap:.1f} IP across all 12 teams.")
    sys.exit(0)


if __name__ == '__main__':
    main()
