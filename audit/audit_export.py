import csv
import io
from datetime import datetime
from openpyxl import Workbook
import tempfile
import os

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

def export_audit_xlsx(get_conn, start_date, end_date):
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

    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Logs"

    # header
    ws.append([
        "action",
        "actor",
        "target",
        "channel",
        "message_id",
        "detail",
        "created_at"
    ])

    for row in rows:
        ws.append([
            row[0],  # action
            row[1],  # actor
            row[2],  # target
            row[3],  # channel
            row[4],  # message_id
            row[5],  # detail
            row[6].strftime("%Y-%m-%d %H:%M:%S")
        ])

    filename = f"audit_{start_date}_{end_date}.xlsx"
    path = os.path.join(tempfile.gettempdir(), filename)
    wb.save(path)

    return path, len(rows)