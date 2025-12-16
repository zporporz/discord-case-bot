import csv
import io
from datetime import datetime

def export_audit_csv(get_conn, start_date, end_date):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    action,
                    actor,
                    target,
                    channel,
                    message_id,
                    detail,
                    created_at
                FROM audit_logs
                WHERE created_at::date BETWEEN %s AND %s
                ORDER BY created_at ASC
            """, (start_date, end_date))

            rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "action",
        "actor",
        "target",
        "channel",
        "message_id",
        "detail",
        "created_at"
    ])

    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return output, len(rows)
