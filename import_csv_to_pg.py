import csv
import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

CSV_PATH = "cases.csv"

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

count = 0
with open(CSV_PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        cur.execute("""
            INSERT INTO cases (date, name, channel, cases, message_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
        """, (
            row["date"],
            row["name"],
            row["channel"],
            int(row["cases"]),
            row["message_id"]
        ))
        count += 1

conn.commit()
cur.close()
conn.close()

print(f"✅ Import finished: {count} rows processed")
