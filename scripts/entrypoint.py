"""
Deploy entrypoint: bootstrap the pipeline against DATABASE_URL if the
integrated tables don't exist yet, then hand off to Streamlit.

Runs once per fresh deployment. Idempotent — if fact_failure_events already
has rows, the bootstrap is skipped and it goes straight to serving.
"""
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from db import get_engine

HERE = os.path.dirname(__file__)


def needs_bootstrap():
    engine = get_engine()
    try:
        with engine.begin() as conn:
            n = conn.execute(text("SELECT count(*) FROM fact_failure_events")).scalar()
        return n == 0
    except ProgrammingError:
        return True


def run(cmd, cwd=None):
    print(f"== {' '.join(cmd)} ==", flush=True)
    subprocess.run(cmd, check=True, cwd=cwd)


def main():
    if needs_bootstrap():
        print("Integrated tables empty/missing — bootstrapping pipeline...", flush=True)
        run([sys.executable, "generate_data.py"], cwd=os.path.join(HERE, "..", "data"))
        run([sys.executable, "run_pipeline.py"], cwd=HERE)
    else:
        print("Integrated tables already populated — skipping bootstrap.", flush=True)

    port = os.environ.get("PORT", "8501")
    os.execvp(
        "streamlit",
        [
            "streamlit",
            "run",
            os.path.join(HERE, "..", "dashboard", "app.py"),
            "--server.port",
            port,
            "--server.address",
            "0.0.0.0",
        ],
    )


if __name__ == "__main__":
    main()
