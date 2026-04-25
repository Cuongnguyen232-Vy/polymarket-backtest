"""
reset_db.py — Reset database for PolyM fresh start
Drops all old PolyM data and recreates clean tables.
"""
import os
import psycopg2

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL")

def reset():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    tables = ["bot_log", "positions", "trades", "daily_summary", "markets", "bot_config"]
    
    for t in tables:
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
        print(f"  ✗ Dropped: {t}")
    
    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ All old PolyM tables dropped!")
    print("Now re-creating fresh PolyM tables...\n")
    
    from db import Database
    db = Database()
    db.create_tables()
    
    # Set initial config for PolyM
    db.set_config("bot_name", "PolyM Paper Bot")
    db.set_config("initial_balance", "10000")
    db.set_config("balance", "10000")
    db.set_config("start_date", str(os.popen("python -c \"from datetime import date; print(date.today())\"").read().strip()))
    
    print("✅ PolyM database initialized with $10,000 starting balance!")

if __name__ == "__main__":
    print("=" * 50)
    print("  PolyM Database Reset")
    print("=" * 50)
    reset()
