"""Run the full FleetGuard pipeline end to end: load raw -> crosswalk/dims ->
reconcile failures -> DQ checks -> reliability stats -> render lineage docs."""
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
SQL_DIR = os.path.join(ROOT, "sql")


def run_sql(*files):
    for fname in files:
        print(f"-- applying {fname}")
        subprocess.run(
            f"docker exec -i fleetguard_pg psql -U fleetguard -d fleetguard < {os.path.join(SQL_DIR, fname)}",
            shell=True,
            check=True,
        )


def run_py(script):
    print(f"== running {script} ==")
    subprocess.run([sys.executable, os.path.join(HERE, script)], check=True, cwd=HERE)


def main():
    run_py("load_raw.py")
    run_sql("02_normalize_functions.sql", "03_crosswalk_and_dim.sql", "04_fact_telemetry.sql")
    run_py("transform.py")
    run_py("dq_checks.py")
    run_py("reliability.py")
    run_py("render_lineage.py")
    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
