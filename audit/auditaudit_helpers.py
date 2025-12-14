# audit/audit_helpers.py
def find_duplicate_person_in_message(get_conn):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT message_id, name, COUNT(*)
                FROM cases
                GROUP BY message_id, name
                HAVING COUNT(*) > 1
            """)
            return cur.fetchall()
