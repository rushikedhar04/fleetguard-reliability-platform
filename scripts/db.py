"""Shared Postgres connection helper. Reads DATABASE_URL, falls back to local docker-compose defaults."""
import os
from sqlalchemy import create_engine

DEFAULT_URL = "postgresql+psycopg2://fleetguard:fleetguard@localhost:5433/fleetguard"


def get_engine():
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    # Render/Railway often hand back "postgres://" — SQLAlchemy needs the psycopg2 dialect prefix.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return create_engine(url)
