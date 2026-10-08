"""Separate disposable CI acceptance phases without weakening production limits."""

import os

import psycopg

from verify_photo_persistence import validate_target


def reset_throttles(connection):
    connection.execute("DELETE FROM public.auth_throttles")


def main():
    database = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://", 1)
    base = os.environ.get("E2E_BASE_URL", "").rstrip("/")
    validate_target(database, base)
    if os.environ.get("E2E_LOGIN") != "e2e-worker":
        raise SystemExit("Synthetic e2e-worker acceptance accounts required")
    with psycopg.connect(database, connect_timeout=5) as connection:
        reset_throttles(connection)
    print("PASS: disposable CI auth counters reset between acceptance phases")


if __name__ == "__main__":
    main()
