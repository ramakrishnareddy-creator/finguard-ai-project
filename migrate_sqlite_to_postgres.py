"""One-time migration of existing FinGuard AI SQLite users/transactions to PostgreSQL.
Run from the project folder after setting DATABASE_URL and installing requirements.
Make a backup of finguard.db first. This script does not print database credentials.
"""
import os
import sqlite3
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = ROOT / "finguard.db"

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is missing. Add your External Database URL to .env first.")
if not SQLITE_PATH.exists():
    raise SystemExit(f"SQLite database not found: {SQLITE_PATH}. Put this script beside finguard.db.")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

source = sqlite3.connect(str(SQLITE_PATH))
source.row_factory = sqlite3.Row
target = psycopg2.connect(DATABASE_URL, sslmode="require")
try:
    with target:
        with target.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS users(
                id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS transactions(
                id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                amount DOUBLE PRECISION NOT NULL, kind TEXT NOT NULL, location TEXT NOT NULL,
                merchant TEXT NOT NULL, tx_time TEXT NOT NULL, score INTEGER NOT NULL,
                level TEXT NOT NULL, reasons TEXT NOT NULL, status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL)""")
            users = source.execute("SELECT id, username, password_hash, role FROM users ORDER BY id").fetchall()
            if users:
                execute_values(cur,
                    "INSERT INTO users(id, username, password_hash, role) VALUES %s ON CONFLICT (id) DO NOTHING",
                    [tuple(row) for row in users])

            txns = source.execute("""SELECT id, user_id, amount, kind, location, merchant, tx_time,
                score, level, reasons, status, created_at FROM transactions ORDER BY id""").fetchall()
            if txns:
                execute_values(cur, """INSERT INTO transactions
                    (id,user_id,amount,kind,location,merchant,tx_time,score,level,reasons,status,created_at)
                    VALUES %s ON CONFLICT (id) DO NOTHING""", [tuple(row) for row in txns])

            # Keep generated IDs above the imported maximum.
            cur.execute("SELECT setval(pg_get_serial_sequence('users','id'), COALESCE((SELECT MAX(id) FROM users), 1), true)")
            cur.execute("SELECT setval(pg_get_serial_sequence('transactions','id'), COALESCE((SELECT MAX(id) FROM transactions), 1), true)")
    print(f"Migration complete. Read {len(users)} users and {len(txns)} transactions from SQLite.")
    print("Existing PostgreSQL rows with matching IDs were left unchanged.")
finally:
    source.close()
    target.close()
