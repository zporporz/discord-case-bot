# audit/case_audit.py
import psycopg2
from datetime import datetime, timedelta


class CaseAudit:
    def __init__(self, get_conn):
        self.get_conn = get_conn

    # 1️⃣ หา message_id ซ้ำ
    def find_duplicate_messages(self):
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT message_id, COUNT(*)
                    FROM cases
                    GROUP BY message_id
                    HAVING COUNT(*) > 1
                """)
                return cur.fetchall()

    # 2️⃣ คนเดียวกันซ้ำใน message เดียว
    def find_duplicate_person_in_message(self):
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT message_id, name, COUNT(*)
                    FROM cases
                    GROUP BY message_id, name
                    HAVING COUNT(*) > 1
                """)
                return cur.fetchall()

    # 3️⃣ เคสเก่ากว่า N วัน (เอาไว้เช็ก edit ข้ามวัน)
    def find_old_cases(self, days=1):
        cutoff = datetime.now().date() - timedelta(days=days)
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, date, message_id
                    FROM cases
                    WHERE date < %s
                """, (cutoff,))
                return cur.fetchall()
