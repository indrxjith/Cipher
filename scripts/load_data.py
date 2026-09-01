"""
load_data.py
CIPHER - Loads the 5 generated CSVs into cipher_db, in dependency order.

Credentials are read from a local .env file (see .env.example) rather than
being hardcoded, so they never end up committed to git.
"""

import os
import pandas as pd
from sqlalchemy import create_engine
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()  # reads .env in the project root, if present

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ["DB_NAME"]

DATA_DIR = "../data"

encoded_password = quote_plus(DB_PASSWORD)

engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Order matters: dimensions first, then the fact table (foreign keys)
TABLES_IN_ORDER = [
    ("dim_user.csv", "dim_user"),
    ("dim_device.csv", "dim_device"),
    ("dim_location.csv", "dim_location"),
    ("dim_application.csv", "dim_application"),
    ("fact_login_events.csv", "fact_login_events"),
]

with engine.begin() as conn:
    # Clear existing data first (safe to re-run), respecting FK order
    for _, table in reversed(TABLES_IN_ORDER):
        conn.exec_driver_sql(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;")

    for csv_file, table in TABLES_IN_ORDER:
        path = f"{DATA_DIR}/{csv_file}"
        df = pd.read_csv(path)
        df.to_sql(table, con=conn, if_exists="append", index=False)
        print(f"Loaded {len(df)} rows into {table}")

print("\nDone. Row counts:")
with engine.connect() as conn:
    for _, table in TABLES_IN_ORDER:
        count = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar()
        print(f"  {table}: {count} rows")