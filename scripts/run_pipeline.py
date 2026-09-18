"""Run the full FleetGuard pipeline end to end: load raw -> crosswalk/dims ->
reconcile failures -> DQ checks -> reliability stats -> render lineage docs.

Works against any Postgres reachable via the DATABASE_URL env var (local
docker-compose default, or a deployed instance like Railway's) — SQL files
are applied through SQLAlchemy, not a docker-specific shell-out."""
import os
import subprocess
import sys

from sqlalchemy import text

from db import get_engine

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
SQL_DIR = os.path.join(ROOT, "sql")


def run_sql(*files):
    engine = get_engine()
    for fname in files:
        print(f"-- applying {fname}")
        with open(os.path.join(SQL_DIR, fname)) as f:
            sql = f.read()
        with engine.begin() as conn:
            conn.execute(text(sql))


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
