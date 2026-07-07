"""Run every tests/test_*.py and report a single pass/fail summary.

    venv/bin/python -m tests.run_all
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    mods = sorted(f[:-3] for f in os.listdir(HERE)
                  if f.startswith("test_") and f.endswith(".py"))
    failed = []
    for m in mods:
        print(f"\n### {m}")
        try:
            runpy.run_module(f"tests.{m}", run_name="__main__")
        except SystemExit as e:
            if e.code:
                failed.append(m)
        except Exception as e:  # a crash counts as a failure, keep going
            print(f"  ERROR {e}")
            failed.append(m)
    print("\n" + "=" * 40)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)
    print(f"ALL GREEN — {len(mods)} suites passed")


if __name__ == "__main__":
    main()
